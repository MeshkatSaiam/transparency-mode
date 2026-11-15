# 🎧 Transparency Mode

A lightweight, ultra-low-latency Windows desktop application built with **Python**, **CustomTkinter**, **SoundDevice**, **NumPy**, and **SciPy**.

Transparency Mode routes your microphone input directly into your headphones in real-time, allowing you to hear your surrounding environment and conversations clearly without taking off your closed-back or noise-isolating headphones.

---

## ✨ Features

- **⚡ Ultra-Low Latency WASAPI Streaming**: Employs real-time full-duplex PortAudio streams (`sd.Stream`) prioritizing **Windows WASAPI** devices with minimal buffer blocksizes (128 / 256 frames, giving **~2.7 ms to 5.3 ms** hardware latency).
- **🎙️ Voice Boost (300 Hz – 3400 Hz Speech Bandpass)**: Real-time 2nd-order Butterworth IIR filter (implemented via Second-Order Sections `sosfilt` with persistent `zi` state) that strips away low-frequency HVAC/fan room rumbles and high-frequency coil hiss while keeping human voice formants crisp and intelligible.
- **🔊 Passthrough Gain Control**: 0% to 200% volume slider with soft tanh saturation limiting to prevent digital clipping pops.
- **⌨️ Global Hotkey (`Ctrl + Alt + T`)**: Seamlessly toggle transparency mode on or off system-wide while working inside any other window or fullscreen game.
- **📊 Real-time VU Meter**: Smooth animated decibel/peak level bar for immediate visual feedback of microphone activity.
- **🔄 Auto-Discovery & Smart Device Prioritization**: Automatically sorts WASAPI input/output devices to the top and detects headphone endpoints.
- **🎨 Modern Windows 11 Dark UI**: Built with CustomTkinter for a sleek, dark-mode native desktop look and feel.

---

## 🛠️ Tech Stack & Architecture

- **GUI**: [CustomTkinter](https://customtkinter.tomschimansky.com/) (modern responsive UI framework)
- **Audio I/O**: [sounddevice](https://python-sounddevice.readthedocs.io/) & PortAudio (WASAPI duplex streaming)
- **DSP & Filtering**: [SciPy Signal](https://docs.scipy.org/doc/scipy/reference/signal.html) (`signal.butter`, `signal.sosfilt_zi`, `signal.sosfilt`) & [NumPy](https://numpy.org/)
- **Global Hotkey**: [keyboard](https://github.com/boppreh/keyboard)

### Signal Flow:
```
Microphone In (WASAPI)
       │
       ▼
[ sd.Stream duplex callback (blocksize: 128 / 256) ]
       │
       ├─► Voice Boost Filter (300 Hz - 3400 Hz Butterworth SOS) [Optional]
       │
       ├─► Passthrough Gain (0% - 200%)
       │
       ├─► Soft Limiter (tanh saturation on peaks > 0.95)
       │
       ├─► Live Peak & RMS Metering
       │
       ▼
Headphones Out (WASAPI)
```

---

## 🚀 Quick Start

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.9+** (Python 3.11 recommended)

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/MeshkatSaiam/transparency-mode.git
cd transparency-mode
pip install -r requirements.txt
```

### 3. Run the Application
Launch via terminal:
```bash
python app.py
```
Or simply double-click `run.bat` on Windows.

---

## 🎹 Keyboard Shortcuts

| Shortcut | Action | Scope |
| :--- | :--- | :--- |
| `Ctrl + Alt + T` | Toggle Transparency Mode (ON / OFF) | Global (any app / game) |

---

## ⚙️ Configuration & Tips

1. **Lowest Latency**: Keep the buffer size set to **128 (2.7 ms)** or **256 (5.3 ms)**. WASAPI shared/exclusive mode provides the lowest achievable latency on Windows.
2. **Room Noise Suppression**: Turn on the **Voice Boost** switch when in noisy rooms or around loud PC fans.
3. **Prevent Feedback**: Keep your microphone away from open desktop speakers, or use closed-back headphones.

---

## 📄 License

MIT License. Feel free to use, modify, and distribute.
