import os
import sys
import json
import re
import asyncio
from typing import Optional

import requests
import pandas as pd
import streamlit as st
import websockets


# --- Path setup (keep if you rely on sibling modules elsewhere) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

st.set_page_config(layout="wide")
st.title("AI Transcriber")


# =========================
# Session state + helpers
# =========================
def _init_state() -> None:
    if "transcribing" not in st.session_state:
        st.session_state.transcribing = False

    # Queue holds items in upload order.
    # Each item: {"order": int, "file_name": str, "job_id": str, "file_id": str, "status": str}
    if "queue" not in st.session_state:
        st.session_state.queue = []
    if "queue_counter" not in st.session_state:
        st.session_state.queue_counter = 0

    # Simple log buffer (strings)
    if "logs" not in st.session_state:
        st.session_state.logs = []


def _enqueue(file_name: str, job_id: str, file_id: str) -> None:
    st.session_state.queue_counter += 1
    st.session_state.queue.append(
        {
            "order": st.session_state.queue_counter,
            "file_name": file_name,
            "job_id": job_id,
            "file_id": file_id,
            "status": "queued",
        }
    )


def _set_status_by_file_id(file_id: str, status: str) -> bool:
    for item in st.session_state.queue:
        if item.get("file_id") == file_id:
            item["status"] = status
            return True
    return False


def _mark_first_queued_transcribing() -> None:
    for item in st.session_state.queue:
        if item.get("status") == "queued":
            item["status"] = "transcribing"
            return


def _pop_first_transcribing_or_first() -> None:
    # Prefer removing the one marked "transcribing"; fallback to FIFO.
    for i, item in enumerate(st.session_state.queue):
        if item.get("status") == "transcribing":
            st.session_state.queue.pop(i)
            return
    if st.session_state.queue:
        st.session_state.queue.pop(0)


def _append_log(msg: str) -> None:
    st.session_state.logs.append(msg)


def _extract_file_id_from_started(msg: str) -> Optional[str]:
    """
    Tries to parse "Transcription started for <fileId>_<filename>"
    """
    m = re.search(r"started\s+for\s+([^_\s]+)_", msg, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _render_queue(container):
    container.empty()  # IMPORTANT: clears previous element in this placeholder

    if not st.session_state.queue:
        container.info("Queue is empty.")
        return

    df = pd.DataFrame(st.session_state.queue)
    for col in ["order", "file_name", "job_id", "status"]:
        if col not in df.columns:
            df[col] = ""

    df = df[["order", "file_name", "job_id", "status"]].sort_values("order")

    container.dataframe(df, hide_index=True, use_container_width=True)


def _render_logs(container, last_n: int = 200):
    container.empty()

    if not st.session_state.logs:
        container.info("No logs yet.")
        return

    with container.expander(label="Live Updates", expanded=True):
        text = "\n".join(st.session_state.logs[-last_n:])
        st.code(text, language=None)


_init_state()


# =========================
# Upload UI
# =========================
st.subheader("Upload Audio File")

with st.form(key="upload_form"):
    file = st.file_uploader(
        label="Select Audio File",
        type=["mp3", "wav", "m4a", "flac", "aac", "ogg", "webm"],
    )
    language = st.selectbox(
        "Language",
        options=["auto", "en", "fr"],
        index=0,
        help="Use 'auto' if you want the backend to detect language.",
    )
    prompt = st.text_area(
        "Prompt (optional)",
        value="",
        placeholder="Optional context for the transcription model (names, jargon, topic, etc.)",
    )
    submitted = st.form_submit_button("Upload")

if submitted:
    if file is None:
        st.warning("Please select a file first.")
    else:
        audioFile = {"audioFile": (file.name, file.read(), file.type)}
        data = {"language": language, "prompt": prompt or ""}
        upload_url = "http://localhost:8000/upload"

        with st.spinner("Uploading..."):
            try:
                resp = requests.post(upload_url, files=audioFile, data=data, timeout=120)
                resp.raise_for_status()

                # Expected: {"jobId": "...", "fileId": "..."}
                try:
                    payload = resp.json()
                except Exception:
                    payload = {}

                job_id = payload.get("jobId")
                file_id = payload.get("fileId")

                if not job_id or not file_id:
                    st.warning(
                        f"Upload succeeded, but backend did not return jobId/fileId. Raw response: {resp.text}"
                    )
                else:
                    _enqueue(file.name, job_id, file_id)
                    st.success(f"Queued: {file.name} (Job ID: {job_id})")
                    st.session_state.transcribing = True

            except Exception as e:
                st.error(e)


# =========================
# Progress + Queue + Logs
# =========================
st.divider()
st.subheader("Progress")

progress_bar = st.progress(value=0)
progress_value = st.metric(label="Progress", value="0%")


def update_progress(percent: float) -> None:
    # percent is between 0 and 1
    percent = max(0.0, min(1.0, float(percent)))
    progress_bar.progress(value=percent)
    progress_value.metric(label="Progress", value=f"{percent*100:.1f}%")


st.divider()
st.subheader("Queue")

queue_container = st.empty()
_render_queue(queue_container)

col_q1, col_q2, col_q3 = st.columns([1, 1, 2])

st.divider()
st.subheader("Logs")


# =========================
# WebSocket listener
# =========================
async def connect_to_websocket(queue_ph, logs_ph):
    async with websockets.connect("ws://localhost:8000/ws") as websocket:
        while st.session_state.transcribing is True:
            try:
                response_str = await websocket.recv()
                response = json.loads(response_str)
                msg = response.get("message", "")

                _append_log(msg)
                _render_logs(logs_ph)

                if "Transcription started" in msg:
                    update_progress(0)
                    file_id = _extract_file_id_from_started(msg)
                    if file_id:
                        if not _set_status_by_file_id(file_id, "transcribing"):
                            # If we can't find it, just mark the next queued item
                            _mark_first_queued_transcribing()
                    else:
                        _mark_first_queued_transcribing()

                    _render_queue(queue_ph)

                elif re.search(r"Chunk\s\d+\/\d+", msg):
                    # Look for a percentage like "12.34%"
                    match = re.search(r"([\d+.]+)%", msg)
                    if match:
                        pct = float(match.group(1)) / 100.0
                        update_progress(pct)

                elif "Transcription finished" in msg:
                    _pop_first_transcribing_or_first()
                    _render_queue(queue_ph)

                    # Stop listening only when the queue is truly empty
                    if not st.session_state.queue:
                        st.session_state.transcribing = False

            except websockets.exceptions.ConnectionClosedOK:
                st.error("WebSocket connection closed gracefully.")
                break
            except Exception as e:
                st.error(f"An error occurred: {e}")
                break


if st.session_state.transcribing:
    with st.spinner(text="In Progress", show_time=True):
        with col_q1:
            if st.button("Clear queue"):
                st.session_state.queue = []
                st.session_state.transcribing = False
                _render_queue(queue_container)
        
        logs_container = st.empty()
        _render_logs(logs_container)

        col_l1, col_l2 = st.columns([1, 5])
        with col_l1:
            if st.button("Clear logs"):
                st.session_state.logs = []
                _render_logs(logs_container)

        asyncio.run(connect_to_websocket(queue_container, logs_container))
else:
    st.info("No active transcription.")


# =========================
# Available transcriptions
# =========================
st.divider()
st.subheader("Available Transcriptions")


@st.fragment
def transcription_list():
    refresh_transcriptions = st.button("Refresh Transcriptions")
    transcriptions_container = st.empty()

    def load_transcriptions(container):
        try:
            response = requests.get("http://localhost:8000/transcriptions", timeout=30)
            response.raise_for_status()
            data = pd.DataFrame(response.json())

            if data.empty:
                container.info("No transcriptions available yet.")
                return

            if "transcribed_on" in data.columns:
                data["transcribed_on"] = pd.to_datetime(data["transcribed_on"], unit="s")

            # Expecting: original_filename, transcribed_on, download_url
            cols = [
                c
                for c in ["original_filename", "transcribed_on", "download_url"]
                if c in data.columns
            ]
            if not cols:
                container.warning("Unexpected response format from /transcriptions.")
                container.write(data)
                return

            container.data_editor(
                data[cols],
                hide_index=True,
                key="transcriptions_list",
                column_config={
                    "original_filename": "File Name",
                    "transcribed_on": "Transcribed On",
                    "download_url": st.column_config.LinkColumn(
                        "Download File", display_text="Download"
                    ),
                },
                disabled=cols,
                use_container_width=True,
            )

        except requests.exceptions.RequestException as e:
            container.error(f"Error connecting to FastAPI backend: {e}")

    if refresh_transcriptions:
        transcriptions_container.empty()
        load_transcriptions(transcriptions_container)

    elif "tx_init" not in st.session_state:
        st.session_state.tx_init = True
        load_transcriptions(transcriptions_container)


transcription_list()
