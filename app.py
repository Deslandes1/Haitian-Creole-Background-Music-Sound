import streamlit as st
import os
import subprocess
import requests
import shutil
from groq import Groq

# yt-dlp (optional)
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    st.warning("yt-dlp not installed. For YouTube/Dropbox links, install it: pip install yt-dlp")

# ================== Check FFmpeg ==================
FFMPEG_PATH = shutil.which("ffmpeg")
if FFMPEG_PATH:
    st.sidebar.success(f"✅ FFmpeg found: {FFMPEG_PATH}")
else:
    st.sidebar.error("❌ FFmpeg not found. Make sure 'packages.txt' contains 'ffmpeg' and redeploy.")
    st.stop()

# Optional: set environment variable for libraries that need it
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_PATH

# ================== Page Config ==================
st.set_page_config(
    page_title="Haitian Creole Speech-to-Captions | GlobalInternet.py",
    page_icon="🇭🇹",
    layout="wide"
)

# ================== Custom CSS ==================
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f3460 0%, #1a1a2e 100%);
        border-right: 2px solid #e94560;
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stCaption {
        color: #ffffff !important;
    }
    h1, h2, h3 {
        color: #ffd966 !important;
    }
    p, li, .stMarkdown, .stCaption, .footer {
        color: #ffffff !important;
    }
    .footer {
        text-align: center;
        margin-top: 2rem;
        padding: 1rem;
        border-top: 1px solid #e94560;
    }
    .stButton>button {
        background-color: #e94560 !important;
        color: white !important;
        border-radius: 30px !important;
        font-weight: bold !important;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #ff6b6b !important;
        transform: scale(1.02);
    }
    .status-box {
        background: rgba(11, 19, 41, 0.7);
        padding: 20px;
        border-radius: 8px;
        border-left: 5px solid #00ebc7;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ================== Helper Functions ==================
def get_duration(file_path):
    if not os.path.exists(file_path):
        return 0.0
    cmd = [FFMPEG_PATH, "-i", file_path, "-f", "null", "-"]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    import re
    match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})", result.stderr)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0

def extract_audio(video_path, audio_output):
    cmd = [FFMPEG_PATH, "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", audio_output, "-y"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(audio_output)

def transcribe_audio_groq(audio_path, groq_client):
    with open(audio_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_path, audio_file.read()),
            model="whisper-large-v3",
            language="ht",  # Haitian Creole
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    return transcription

def generate_srt_from_segments(segments, output_srt):
    def fmt_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    with open(output_srt, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start = seg.start
            end = seg.end
            text = seg.text.strip()
            if not text:
                continue
            f.write(f"{i}\n")
            f.write(f"{fmt_time(start)} --> {fmt_time(end)}\n")
            f.write(f"{text}\n\n")

def mix_audio_with_music(original_audio, music_audio, output_audio, music_volume=0.3):
    cmd = [
        FFMPEG_PATH, "-i", original_audio, "-i", music_audio,
        "-filter_complex", f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first",
        "-ac", "2", "-c:a", "aac", "-b:a", "128k",
        output_audio, "-y"
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(output_audio)

def burn_subtitles(video_path, audio_path, srt_path, output_video):
    cmd = [
        FFMPEG_PATH, "-i", video_path, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", f"subtitles={srt_path}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        output_video, "-y"
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(output_video)

def download_file(url, output_path):
    """Download any file (video or audio) from Dropbox/URL using yt-dlp or aria2c"""
    if "dropbox.com" in url and "dl=0" in url:
        url = url.replace("dl=0", "dl=1")
    elif "dropbox.com" in url and "?dl=" not in url:
        url = url + "?dl=1"
    # Try aria2c first (often installed)
    try:
        cmd = ["aria2c", "-x", "16", "-s", "16", "-k", "1M", "--console-log-level=error", "-o", output_path, url]
        subprocess.run(cmd, check=True, timeout=600)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
    except:
        pass
    # Fallback to yt-dlp
    if YT_DLP_AVAILABLE:
        try:
            ydl_opts = {'outtmpl': output_path, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return os.path.exists(output_path)
        except:
            pass
    # Direct HTTP fallback
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192*16):
                f.write(chunk)
        return os.path.exists(output_path)
    except:
        return False

# ================== Sidebar ==================
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; margin-bottom: 20px;">
        <div style="font-size: 60px;">🌍</div>
        <h2 style="color: #ffd966; margin: 0;">GlobalInternet.py</h2>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("**Built by Gesner Deslandes** – Engineer-in-Chief")
    st.markdown("📞 (509) 4738 5663")
    st.markdown("✉️ deslandes78@gmail.com")
    st.markdown("---")
    st.markdown("### 🇭🇹 Haitian Creole Captioner")
    st.markdown("""
    - Upload a video with Haitian Creole speech
    - AI transcribes words into captions
    - Add background music (optional)
    - Download final video with subtitles
    """)
    st.markdown("---")
    st.markdown("### 💰 Need a custom version?")
    st.markdown("Contact us for source code or customization.")

# ================== Main Interface ==================
image_url = "https://raw.githubusercontent.com/Deslandes1/Haitian-Creole-Background-Music-Sound/main/Gesner%20Deslandes.png"
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("<h1 style='text-align:right; margin-bottom:0;'>🇭🇹 Haitian Creole Speech-to-Captions</h1>", unsafe_allow_html=True)
with col2:
    try:
        st.image(image_url, width=60)
    except:
        st.markdown("📸")

st.markdown("### Upload a video (or paste a Dropbox link) – AI will transcribe your Haitian Creole speech and add captions with background music.")

col_left, col_right = st.columns([2, 1.8])

with col_left:
    st.markdown('<div class="feature-card" style="background: rgba(255,255,255,0.04); border-radius: 12px; padding: 20px;">', unsafe_allow_html=True)
    st.markdown("#### 1. Source Video (Haitian Creole speech)")
    input_method = st.radio("Choose input method:", ["Upload video from computer", "Paste Dropbox/YouTube link"], horizontal=True)
    video_path_input = None
    video_url = None
    
    if input_method == "Upload video from computer":
        uploaded_file = st.file_uploader("Select MP4/MOV/AVI file", type=["mp4", "mov", "avi", "mkv"])
        if uploaded_file:
            video_path_input = "uploaded_video.mp4"
            with open(video_path_input, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.video(video_path_input)
    else:
        video_url = st.text_input("Video link (Dropbox, YouTube, direct MP4):", 
                                 value="https://www.dropbox.com/scl/fi/yzg1adtnbldj5l6zoo54j/Color-game.mp4?rlkey=4eetqcb4xcqf6nlqi8eijcsbs&st=sz2ryrro&dl=0")
        if video_url:
            st.info("Video will be downloaded automatically when you click 'Transcribe & Create Video'.")
    
    st.markdown("---")
    st.markdown("#### 2. Background Music (Optional)")
    music_option = st.radio("Music source:", ["No music", "Upload my own music", "Dropbox link (MP3)"], horizontal=False)
    music_path = None
    music_url = None
    
    if music_option == "Upload my own music":
        music_file = st.file_uploader("Upload MP3/WAV", type=["mp3", "wav"])
        if music_file:
            music_path = "bg_music.mp3"
            with open(music_path, "wb") as f:
                f.write(music_file.getbuffer())
            st.audio(music_path)
    elif music_option == "Dropbox link (MP3)":
        music_url = st.text_input("Dropbox link to MP3 file:", 
                                 value="https://www.dropbox.com/s/example.mp3?dl=0")
        if music_url:
            st.info("Music will be downloaded automatically when you click 'Transcribe & Create Video'.")
    
    st.markdown('</div>', unsafe_allow_html=True)

with col_right:
    st.markdown('<div class="feature-card" style="background: rgba(255,255,255,0.04); border-radius: 12px; padding: 20px;">', unsafe_allow_html=True)
    st.markdown("#### 3. Generate Captions & Music")
    st.markdown(f"**Transcription language:** Haitian Creole (ht)")
    music_volume = st.slider("Background music volume (if added)", 0.0, 1.0, 0.3, step=0.05)
    generate_btn = st.button("🎤 Transcribe & Create Video", use_container_width=True)

    if generate_btn:
        # Validate video source
        if input_method == "Upload video from computer":
            if not video_path_input or not os.path.exists(video_path_input):
                st.error("Please upload a video file first.")
                st.stop()
        else:  # Paste link
            if not video_url:
                st.error("Please provide a video link.")
                st.stop()
            else:
                # Download video
                with st.spinner("Downloading video from link..."):
                    video_path_input = "downloaded_video.mp4"
                    if not download_file(video_url, video_path_input):
                        st.error("Failed to download video. Check the link and try again.")
                        st.stop()
                    st.success("Video downloaded successfully!")
        
        # Download music if needed
        if music_option == "Dropbox link (MP3)" and music_url:
            with st.spinner("Downloading background music..."):
                music_path = "bg_music_downloaded.mp3"
                if not download_file(music_url, music_path):
                    st.warning("Failed to download music. Proceeding without background music.")
                    music_path = None
                else:
                    st.success("Music downloaded successfully!")
        elif music_option == "Upload my own music":
            # music_path already set
            pass
        else:
            music_path = None
        
        # Now run the main pipeline
        if "GROQ_API_KEY" not in st.secrets:
            st.error("Missing Groq API key. Add GROQ_API_KEY to your Streamlit secrets.")
            st.stop()
        
        st.markdown('<div class="status-box">', unsafe_allow_html=True)
        status = st.empty()
        progress = st.progress(0)
        try:
            # Cleanup
            for f in ["extracted_audio.mp3", "captions.srt", "mixed_audio.mp3", "final_output.mp4"]:
                if os.path.exists(f):
                    os.remove(f)

            status.text("📤 Extracting audio from video...")
            progress.progress(10)
            if not extract_audio(video_path_input, "extracted_audio.mp3"):
                raise Exception("Audio extraction failed. Ensure ffmpeg is correctly installed via packages.txt.")

            status.text("🎙️ Transcribing Haitian Creole speech with Groq Whisper...")
            progress.progress(30)
            groq_client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            transcription = transcribe_audio_groq("extracted_audio.mp3", groq_client)
            segments = transcription.segments
            if not segments:
                st.warning("No speech detected or transcription returned empty.")
            else:
                st.info(f"Transcribed {len(segments)} segments.")

            status.text("📝 Generating subtitle file (SRT)...")
            progress.progress(50)
            generate_srt_from_segments(segments, "captions.srt")

            # Handle audio mixing
            if music_path and os.path.exists(music_path):
                status.text("🎵 Mixing background music with original audio...")
                progress.progress(65)
                if not mix_audio_with_music("extracted_audio.mp3", music_path, "mixed_audio.mp3", music_volume):
                    st.warning("Music mixing failed, using original audio.")
                    final_audio = "extracted_audio.mp3"
                else:
                    final_audio = "mixed_audio.mp3"
            else:
                final_audio = "extracted_audio.mp3"

            status.text("🎬 Burning subtitles and creating final video...")
            progress.progress(80)
            if not burn_subtitles(video_path_input, final_audio, "captions.srt", "final_output.mp4"):
                raise Exception("Final video creation failed.")

            progress.progress(100)
            status.text("✅ Done! Your video with Haitian Creole captions is ready.")
            st.markdown('</div>', unsafe_allow_html=True)

            st.success("Video processed successfully!")
            st.video("final_output.mp4")
            with open("final_output.mp4", "rb") as f:
                st.download_button("⬇️ Download Video with Captions", f, file_name="creole_captioned_video.mp4", mime="video/mp4", use_container_width=True)
            with open("captions.srt", "rb") as f:
                st.download_button("📄 Download Captions (SRT)", f, file_name="captions.srt", mime="text/plain", use_container_width=True)

        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="footer">© GlobalInternet.py – AI‑powered Haitian Creole captioning. Built by Gesner Deslandes.</div>', unsafe_allow_html=True)
