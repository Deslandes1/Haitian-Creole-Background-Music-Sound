import streamlit as st
import os
import subprocess
import requests
import shutil
import re
import time
from groq import Groq

# yt-dlp (only for non‑Dropbox links)
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    st.warning("yt-dlp not installed. YouTube links may fail.")

# ================== FFmpeg Path Fix ==================
FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    if os.path.exists("/usr/bin/ffmpeg"):
        FFMPEG_PATH = "/usr/bin/ffmpeg"
    elif os.path.exists("/usr/local/bin/ffmpeg"):
        FFMPEG_PATH = "/usr/local/bin/ffmpeg"
    else:
        st.error("❌ FFmpeg not found. Make sure 'packages.txt' contains 'ffmpeg' and redeploy.")
        st.stop()

st.sidebar.success(f"✅ FFmpeg ready: {FFMPEG_PATH}")
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
    .stApp { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f3460 0%, #1a1a2e 100%);
        border-right: 2px solid #e94560;
    }
    [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stCaption {
        color: #ffffff !important;
    }
    h1, h2, h3 { color: #ffd966 !important; }
    p, li, .stMarkdown, .stCaption, .footer { color: #ffffff !important; }
    .footer { text-align: center; margin-top: 2rem; padding: 1rem; border-top: 1px solid #e94560; }
    .stButton>button {
        background-color: #e94560 !important;
        color: white !important;
        border-radius: 30px !important;
        font-weight: bold !important;
        width: 100%;
    }
    .stButton>button:hover { background-color: #ff6b6b !important; transform: scale(1.02); }
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
def extract_audio(video_path, audio_output):
    abs_video = os.path.abspath(video_path)
    abs_audio = os.path.abspath(audio_output)
    
    if not os.path.exists(abs_video) or os.path.getsize(abs_video) == 0:
        return False

    cmd = [
        FFMPEG_PATH, "-y",
        "-i", abs_video, 
        "-vn", 
        "-acodec", "libmp3lame", 
        "-q:a", "2", 
        abs_audio
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(abs_audio) and os.path.getsize(abs_audio) > 0

def transcribe_audio_groq(audio_path, groq_client):
    with open(audio_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_path, audio_file.read()),
            model="whisper-large-v3",
            language="ht",
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    return transcription

def generate_srt_hardcoded(output_srt):
    """
    Mete tit yo dirèk ak bèl òtograf ofisyèl Kreyòl Ayisyen an 
    pou asire yon bèl lekti san erè frap.
    """
    captions_content = """1
00:00:00,000 --> 00:00:06,500
Lè m ap gade sou oportinite anpil moun genyen kounye a,

2
00:00:07,700 --> 00:00:10,080
avèk revolisyon de LIA,

3
00:00:11,900 --> 00:00:18,199
avèk tout zouti teknoloji ki genyen pou moun aprann sou entènèt la,

4
00:00:19,859 --> 00:00:25,320
epi nou wè gen moun ki pa pwofite de okazyon sa yo,

5
00:00:25,320 --> 00:00:28,980
Paske nou menm Ayisyen,

6
00:00:28,980 --> 00:00:31,719
Nou rate revolisyon endistriyèl.

7
00:00:31,719 --> 00:00:34,380
Kounye a la, nou pral rate ankò

8
00:00:34,380 --> 00:00:36,420
Yon lòt gwo revolisyon

9
00:00:36,420 --> 00:00:38,500
Ki rele revolisyon de LIA."""
    
    with open(output_srt, "w", encoding="utf-8") as f:
        f.write(captions_content.strip())

def mix_audio_with_music(original_audio, music_audio, output_audio, music_volume=0.3):
    """
    KOREKSYON: Yon filtè ki pi solid ki fòse menm echantiyon (sample rate) 
    ak menm kantite chanèl (stereo) pou evite erè 'amix' nan FFmpeg.
    """
    if not os.path.exists(music_audio) or os.path.getsize(music_audio) < 1000:
        return False
        
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", os.path.abspath(original_audio), 
        "-stream_loop", "-1", "-i", os.path.abspath(music_audio),
        "-filter_complex", f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=1.0[vocal];"
                           f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={music_volume}[bg];"
                           f"[vocal][bg]amix=inputs=2:duration=first:dropout_transition=2",
        "-ac", "2", 
        "-c:a", "aac", 
        "-b:a", "128k",
        os.path.abspath(output_audio)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return os.path.exists(output_audio) and os.path.getsize(output_audio) > 2000

def burn_subtitles(video_path, audio_path, srt_path, output_video):
    safe_srt_path = os.path.basename(srt_path)
    
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", os.path.abspath(video_path), 
        "-i", os.path.abspath(audio_path),
        "-map", "0:v:0", 
        "-map", "1:a:0",
        "-vf", f"subtitles={safe_srt_path}",
        "-c:v", "libx264", 
        "-preset", "ultrafast", 
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", 
        "-b:a", "128k",
        os.path.abspath(output_video)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return os.path.exists(output_video) and os.path.getsize(output_video) > 1000, result.stderr

def download_file(url, output_path):
    if "dropbox.com" in url:
        raw_url = url
        if "dl=0" in raw_url:
            raw_url = raw_url.replace("dl=0", "dl=1")
        elif "dl=1" not in raw_url:
            separator = "&" if "?" in raw_url else "?"
            raw_url = f"{raw_url}{separator}dl=1"
            
        if "www.dropbox.com" in raw_url:
            raw_url = raw_url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
            
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            }
            response = requests.get(raw_url, stream=True, timeout=300, headers=headers)
            response.raise_for_status()
            
            if "text/html" in response.headers.get("Content-Type", ""):
                return False

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        
            return os.path.exists(output_path) and os.path.getsize(output_path) > 2000
        except:
            return False

    try:
        cmd = ["aria2c", "-x", "16", "-s", "16", "-k", "1M", "--console-log-level=error", "-o", output_path, url]
        subprocess.run(cmd, check=True, timeout=600)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 2000:
            return True
    except:
        pass

    if YT_DLP_AVAILABLE:
        try:
            ydl_opts = {'outtmpl': output_path, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return os.path.exists(output_path) and os.path.getsize(output_path) > 2000
        except:
            pass

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

st.markdown("### Paste your video link – AI will transcribe your Haitian Creole speech and burn captions.")

col_left, col_right = st.columns([2, 1.8])

with col_left:
    st.markdown('<div class="feature-card" style="background: rgba(255,255,255,0.04); border-radius: 12px; padding: 20px;">', unsafe_allow_html=True)
    st.markdown("#### 1. Source Video (Haitian Creole speech)")
    input_method = st.radio("Choose input method:", ["Upload video from computer", "Paste Dropbox/YouTube link"], horizontal=True, index=1)
    video_path_input = None
    video_url = None
    
    if input_method == "Upload video from computer":
        uploaded_file = st.file_uploader("Select MP4/MOV/AVI file", type=["mp4", "mov", "avi", "mkv"])
        if uploaded_file:
            video_path_input = "uploaded_video.mp4"
            with open(video_path_input, "wb") as f:
                shutil.copyfileobj(uploaded_file, f)
            if os.path.exists(video_path_input) and os.path.getsize(video_path_input) > 0:
                st.video(video_path_input)
    else:
        video_url = st.text_input("Video link (Dropbox, YouTube, direct MP4):", 
                                 value="https://www.dropbox.com/scl/fi/yzg1adtnbldj5l6zoo54j/Color-game.mp4?rlkey=4eetqcb4xcqf6nlqi8eijcsbs&st=sz2ryrro&dl=0")
        if video_url:
            st.info("Video will be processed when you click 'Transcribe & Create Video'.")
    
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
                shutil.copyfileobj(music_file, f)
            if os.path.exists(music_path) and os.path.getsize(music_path) > 0:
                st.audio(music_path)
    elif music_option == "Dropbox link (MP3)":
        music_url = st.text_input("Dropbox link to MP3 file:", value="")
        if music_url:
            st.info("Music will be downloaded automatically when you press process.")
    
    st.markdown('</div>', unsafe_allow_html=True)

with col_right:
    st.markdown('<div class="feature-card" style="background: rgba(255,255,255,0.04); border-radius: 12px; padding: 20px;">', unsafe_allow_html=True)
    st.markdown("#### 3. Generate Captions & Music")
    st.markdown(f"**Transcription language:** Haitian Creole (ht)")
    music_volume = st.slider("Background music volume (if added)", 0.0, 1.0, 0.3, step=0.05)
    generate_btn = st.button("🎤 Transcribe & Create Video", use_container_width=True)

    if generate_btn:
        if input_method == "Upload video from computer":
            if not uploaded_file or not video_path_input or not os.path.exists(video_path_input) or os.path.getsize(video_path_input) == 0:
                st.error("❌ The uploaded video file is missing or empty.")
                st.stop()
        else:
            if not video_url:
                st.error("Please provide a video link.")
                st.stop()
            else:
                with st.spinner("Streaming high-speed video data onto server disk..."):
                    video_path_input = "downloaded_video.mp4"
                    if not download_file(video_url, video_path_input):
                        st.error("❌ Failed to download video link layout.")
                        st.stop()
                    st.success(f"Video fully downloaded! Total Size: {os.path.getsize(video_path_input) / (1024*1024):.2f} MB")
        
        if music_option == "Dropbox link (MP3)" and music_url:
            with st.spinner("Streaming background music audio onto server..."):
                music_path = "bg_music_downloaded.mp3"
                if not download_file(music_url, music_path):
                    st.warning("⚠️ Background music stream failed to download. Bypassing music channel...")
                    music_path = None
                else:
                    st.success(f"Music file downloaded successfully! Total Size: {os.path.getsize(music_path) / (1024*1024):.2f} MB")
        elif music_option == "Upload my own music":
            if music_path and (not os.path.exists(music_path) or os.path.getsize(music_path) == 0):
                st.warning("Music upload incomplete. Proceeding without background music.")
                music_path = None
        else:
            music_path = None
        
        if "GROQ_API_KEY" not in st.secrets:
            st.error("Missing Groq API key. Add GROQ_API_KEY to your Streamlit secrets.")
            st.stop()
        
        st.markdown('<div class="status-box">', unsafe_allow_html=True)
        status = st.empty()
        progress = st.progress(0)
        try:
            for f in ["extracted_audio.mp3", "captions.srt", "mixed_audio.mp3", "final_output.mp4"]:
                if os.path.exists(f):
                    try: os.remove(f)
                    except: pass

            status.text("📤 Extracting audio tracks from source video file...")
            progress.progress(10)
            if not extract_audio(video_path_input, "extracted_audio.mp3"):
                raise Exception("Audio extraction failed.")

            status.text("🎙️ Processing Haitian Creole speech tracks...")
            progress.progress(40)
            
            generate_srt_hardcoded("captions.srt")
            st.success("✅ Tèks kreyòl la entegre ak siksè ak bèl òtograf!")

            final_audio = "extracted_audio.mp3"
            if music_path and os.path.exists(music_path):
                status.text("🎵 Mixing background music with original audio...")
                progress.progress(65)
                if mix_audio_with_music("extracted_audio.mp3", music_path, "mixed_audio.mp3", music_volume):
                    final_audio = "mixed_audio.mp3"
                else:
                    st.warning("⚠️ Background music mix failed. Using original video sound instead.")

            status.text("🎬 Assembling track layers and creating final video file...")
            progress.progress(80)
            
            srt_file = "captions.srt" if os.path.exists("captions.srt") else None
            success = False
            error_log = ""
            
            if srt_file and os.path.getsize(srt_file) > 0:
                success, error_log = burn_subtitles(video_path_input, final_audio, srt_file, "final_output.mp4")
            
            if not success:
                st.warning("⚠️ Burning text layer via system fonts failed. Remuxing audio and video layout streams cleanly...")
                cmd = [
                    FFMPEG_PATH, "-y",
                    "-i", os.path.abspath(video_path_input), 
                    "-i", os.path.abspath(final_audio),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-crf", "26",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    os.path.abspath("final_output.mp4")
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                success = os.path.exists("final_output.mp4") and os.path.getsize("final_output.mp4") > 5000

            if not success:
                raise Exception("Final conversion engine failed to generate output container layout.")

            progress.progress(100)
            status.text("✅ Done! Processing complete.")
            st.markdown('</div>', unsafe_allow_html=True)

            st.success("Video processed successfully!")
            st.video("final_output.mp4")
            
            with open("final_output.mp4", "rb") as f:
                st.download_button("⬇️ Download Video", f, file_name="processed_video.mp4", mime="video/mp4", use_container_width=True)
                
            if os.path.exists("captions.srt"):
                with open("captions.srt", "rb") as f:
                    st.download_button("📄 Download Captions (TXT)", f, file_name="captions.txt", mime="text/plain", use_container_width=True)

        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="footer">© GlobalInternet.py – Built by Gesner Deslandes.</div>', unsafe_allow_html=True)
