# =============================================================================
# GHOSTWRITER - The Human Typing Emulator (FINAL VERSION)
#
# A full GUI application to simulate human typing with advanced features:
# - Typing Profiles
# - Granular pause and error control
# - Delayed error correction and cursor simulation
# - Global hotkeys for control from any window
# - AI-powered paraphrasing
#
# Framework: PySide6
# =============================================================================

import sys
import os
import time
import random
import threading
from dotenv import load_dotenv

# --- PySide6 Imports ---
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QThread, Signal, QObject, Slot
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QTextEdit, QPushButton, QSlider,
                               QLabel, QSpinBox, QProgressBar, QCheckBox,
                               QComboBox, QFrame, QGroupBox)

# --- Core Logic Imports ---
from pynput import keyboard
import google.generativeai as genai

# --- Initial Configuration ---
load_dotenv()
AVG_CHARS_PER_WORD = 5

# =============================================================================
# STYLING (QSS - Qt Style Sheets)
# =============================================================================
DARK_STYLE = """
    /* (omitted for brevity - same as previous version) */
    /* Paste the full DARK_STYLE string from the previous answer here */
    QWidget { background-color: #2b2b2b; color: #f0f0f0; font-family: 'Segoe UI'; font-size: 10pt; }
    QMainWindow { background-color: #2b2b2b; }
    QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 1ex; font-weight: bold; }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 3px; }
    QTextEdit, QSpinBox, QComboBox { background-color: #3c3f41; border: 1px solid #555; border-radius: 4px; padding: 5px; }
    QPushButton { background-color: #4a4d50; border: 1px solid #555; padding: 8px; border-radius: 4px; }
    QPushButton:hover { background-color: #5a5d60; } QPushButton:pressed { background-color: #505356; }
    QPushButton#StartButton { background-color: #357a38; font-weight: bold; } QPushButton#StartButton:hover { background-color: #4a9a4d; }
    QPushButton#StopButton { background-color: #b71c1c; font-weight: bold; } QPushButton#StopButton:hover { background-color: #d32f2f; }
    QSlider::groove:horizontal { border: 1px solid #555; height: 8px; background: #3c3f41; margin: 2px 0; border-radius: 4px; }
    QSlider::handle:horizontal { background: #00bcd4; border: 1px solid #00bcd4; width: 18px; margin: -5px 0; border-radius: 9px; }
    QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; color: white; }
    QProgressBar::chunk { background-color: #00bcd4; border-radius: 4px; }
    QLabel#TitleLabel { font-size: 14pt; font-weight: bold; color: #00bcd4; }
"""

# =============================================================================
# TYPING PROFILES
# =============================================================================
PROFILES = {
    "The Careful Student": {
        "wpm": 55, "error_rate": 2, "correction_delay": 0, "thinking_chance": 5, "thinking_duration": (2, 5),
        "afk_chance": 2, "afk_duration": (30, 90)
    },
    "The Sloppy Rusher": {
        "wpm": 110, "error_rate": 10, "correction_delay": 0, "thinking_chance": 1, "thinking_duration": (1, 2),
        "afk_chance": 0, "afk_duration": (0, 0)
    },
    "The Methodical Writer": {
        "wpm": 70, "error_rate": 5, "correction_delay": 50, "thinking_chance": 10, "thinking_duration": (4, 10),
        "afk_chance": 5, "afk_duration": (60, 180)
    },
    "Custom": None  # Placeholder
}


# (Other worker classes like GeminiParaphraser and WorkerSignals are omitted for brevity - same as before)
# Paste the WorkerSignals, GeminiParaphraser, and ParaphraseWorker classes here from the previous answer.

class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)
    status_update = Signal(str)
    paraphrased_text_ready = Signal(str)


class GeminiParaphraser:
    # ... (Paste the full class from the previous answer)
    def __init__(self):
        self.model = None
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ WARNING: Gemini API key not found. Paraphrasing is disabled.")
            return
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    def paraphrase(self, text, intensity, signals: WorkerSignals):
        if not self.model:
            signals.error.emit("Gemini model not initialized.")
            return text

        prompt = f"""
        Please paraphrase the following text. Rewrite it to be unique while preserving the original meaning, tone, and key information.
        The desired intensity of the rewrite is '{intensity}'.
        Do NOT add any introductory phrases like "Here is the paraphrased text:".
        Output ONLY the rewritten text.

        ORIGINAL TEXT:
        ---
        {text}
        ---
        """
        try:
            signals.status_update.emit("🔄 Sending text to Gemini API...")
            response = self.model.generate_content(prompt)
            paraphrased_text = response.text.strip()
            signals.status_update.emit("✅ Paraphrasing complete.")
            return paraphrased_text
        except Exception as e:
            signals.error.emit(f"Gemini API Error: {str(e)}")
            return text


# =============================================================================
# REWRITTEN CORE TYPING ENGINE
# =============================================================================
class TypingEngine:
    def __init__(self, text, settings, signals: WorkerSignals):
        self.text_to_type = text
        self.settings = settings
        self.signals = signals
        self.keyboard = keyboard.Controller()

        self.is_stopped = False
        self.is_paused = False
        self.uncorrected_errors = []

        # Character-level delay simulation
        self.FAST_KEYS = set("eatisrondlcum")
        self.SLOW_KEYS = set("zjqxkvb")

    def stop(self):
        self.is_stopped = True

    def pause(self):
        self.is_paused = True; self.signals.status_update.emit("⏸️ Paused.")

    def resume(self):
        self.is_paused = False; self.signals.status_update.emit("▶️ Resuming...")

    def _calculate_delays(self):
        # ... (This logic is mostly the same as before)
        # We now also use these values as a base for dynamic pauses
        total_chars = len(self.text_to_type)
        total_duration_sec = self.settings['total_minutes'] * 60
        base_wpm = self.settings['wpm']
        pure_typing_time_sec = (total_chars / AVG_CHARS_PER_WORD) / base_wpm * 60
        if pure_typing_time_sec >= total_duration_sec:
            pure_typing_time_sec = total_duration_sec * 0.95

        total_pause_time_sec = total_duration_sec - pure_typing_time_sec
        self.char_delay = (pure_typing_time_sec / total_chars) if total_chars > 0 else 0.05
        self.wpm_jitter = self.char_delay * 0.25  # Use a fixed jitter for simplicity

        num_words = len(self.text_to_type.split())
        num_sentences = self.text_to_type.count('.') + self.text_to_type.count('!') + self.text_to_type.count('?')
        self.word_pause = (total_pause_time_sec * 0.20) / num_words if num_words > 0 else 0
        self.sentence_pause = (total_pause_time_sec * 0.40) / num_sentences if num_sentences > 0 else 0
        self.paragraph_pause = (total_pause_time_sec * 0.40) / self.text_to_type.count('\n') if self.text_to_type.count(
            '\n') > 0 else 0

    def _get_mistake(self, word):
        # ... (Same as before, but ensure it's robust)
        if len(word) < 3 or not word.isalpha(): return word, None
        mistake_type = random.choice(['adjacency', 'transposition', 'omission', 'insertion'])

        idx = random.randint(0, len(word) - 1)
        if mistake_type == 'adjacency' and len(word) > 1:
            char = word[idx]
            adj_map = {'q': 'w', 'w': 'es', 'e': 'wr', 'r': 'et', 't': 'ry', 'y': 'tu', 'u': 'yi', 'i': 'uo', 'o': 'ip',
                       'p': 'o[', 'a': 's', 's': 'adw', 'd': 'efs', 'f': 'dgr', 'g': 'fht', 'h': 'gjy', 'j': 'hku',
                       'k': 'jli', 'l': 'k;o', ';': 'l', 'z': 'x', 'x': 'zc', 'c': 'xvd', 'v': 'cfb', 'b': 'vgn',
                       'n': 'bhm', 'm': 'njk'}
            if char.lower() in adj_map:
                new_char = random.choice(adj_map[char.lower()])
                return word[:idx] + new_char + word[idx + 1:], word
        elif mistake_type == 'transposition' and len(word) > 1:
            idx = random.randint(0, len(word) - 2)
            return word[:idx] + word[idx + 1] + word[idx] + word[idx + 2:], word
        elif mistake_type == 'omission':
            return word[:idx] + word[idx + 1:], word
        elif mistake_type == 'insertion':
            return word[:idx] + random.choice('aeiou') + word[idx:], word
        return word, None

    def _sleep(self, duration):
        """A pausable, stoppable sleep."""
        end_time = time.time() + duration
        while time.time() < end_time:
            if self.is_stopped: return
            while self.is_paused:
                time.sleep(0.1)
                if self.is_stopped: return
            time.sleep(0.1)

    def _type_char(self, char):
        self.keyboard.type(char)
        delay = self.char_delay
        if char in self.FAST_KEYS:
            delay *= 0.8
        elif char in self.SLOW_KEYS:
            delay *= 1.3
        self._sleep(max(0.02, delay + random.uniform(-self.wpm_jitter, self.wpm_jitter)))

    def _perform_correction(self, incorrect, correct, current_pos, error_pos):
        # Move cursor back
        distance = current_pos - error_pos
        for _ in range(distance): self.keyboard.press(keyboard.Key.left); self.keyboard.release(
            keyboard.Key.left); self._sleep(0.02)

        # Fix error
        for _ in range(len(incorrect)): self.keyboard.press(keyboard.Key.backspace); self.keyboard.release(
            keyboard.Key.backspace); self._sleep(0.05)
        for char in correct: self._type_char(char)

        # Move cursor forward
        for _ in range(distance - len(correct)): self.keyboard.press(keyboard.Key.right); self.keyboard.release(
            keyboard.Key.right); self._sleep(0.02)

    def run(self):
        self._calculate_delays()
        self.signals.status_update.emit("Starting in 5 seconds...")
        self._sleep(5)
        self.signals.status_update.emit("🚀 Typing started!")

        current_pos = 0
        words = self.text_to_type.replace('\n', ' \n ').split(' ')

        for i, word in enumerate(words):
            if self.is_stopped: break

            # --- PRE-WORD ACTIONS ---
            # 1. Delayed Correction Check
            if self.uncorrected_errors and random.randint(1, 100) <= self.settings['correction_delay']:
                error_to_fix = self.uncorrected_errors.pop(0)
                self.signals.status_update.emit(f"🤔 Going back to fix '{error_to_fix['incorrect']}'...")
                self._perform_correction(error_to_fix['incorrect'], error_to_fix['correct'], current_pos,
                                         error_to_fix['pos'])
                self.signals.status_update.emit("✅ Fixed.")

            # 2. Thinking Pause Check
            if random.randint(1, 100) <= self.settings['thinking_chance']:
                duration = random.uniform(*self.settings['thinking_duration'])
                self.signals.status_update.emit(f"🧠 Thinking for {duration:.1f}s...")
                self._sleep(duration)

            # --- TYPING THE WORD ---
            if word.isalpha() and random.random() < (self.settings['error_rate'] / 100):
                incorrect, correct = self._get_mistake(word)
                if correct:
                    # Log error for delayed correction
                    self.uncorrected_errors.append({'incorrect': incorrect, 'correct': correct, 'pos': current_pos})
                    for char in incorrect: self._type_char(char)
                else:
                    for char in word: self._type_char(char)
            else:
                for char in word: self._type_char(char)

            current_pos += len(word) + 1

            # --- POST-WORD ACTIONS ---
            self.signals.progress.emit(int((i / len(words)) * 100))
            if word == '\n':
                if random.randint(1, 100) <= self.settings['afk_chance']:
                    duration = random.uniform(*self.settings['afk_duration'])
                    self.signals.status_update.emit(f"☕ AFK break for {duration:.1f}s...")
                    self._sleep(duration)
                else:
                    self._sleep(self.paragraph_pause)
            elif word.endswith(('.', '!', '?')):
                self._sleep(self.sentence_pause)
            else:
                self._type_char(' '); self._sleep(self.word_pause)

        if not self.is_stopped:
            self.signals.status_update.emit("🎉 Typing finished successfully!")
            self.signals.progress.emit(100)
        else:
            self.signals.status_update.emit("🛑 Typing stopped by user.")


# =============================================================================
# QTHREAD WORKERS (TypingWorker and ParaphraseWorker)
# =============================================================================
class ParaphraseWorker(QObject):
    # ... (Paste the full class from the previous answer)
    def __init__(self, text, intensity):
        super().__init__()
        self.text = text
        self.intensity = intensity
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            paraphraser = GeminiParaphraser()
            if not paraphraser.model:
                self.signals.error.emit("Gemini not initialized (check API key).")
                self.signals.finished.emit()
                return
            result = paraphraser.paraphrase(self.text, self.intensity, self.signals)
            self.signals.paraphrased_text_ready.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class TypingWorker(QObject):
    def __init__(self, text, settings):
        super().__init__()
        self.signals = WorkerSignals()
        self.engine = TypingEngine(text, settings, self.signals)

    @Slot()
    def run(self):
        try:
            self.engine.run()
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# =============================================================================
# GLOBAL HOTKEY LISTENER
# =============================================================================
class GlobalHotkeyListener(threading.Thread):
    def __init__(self, main_window):
        super().__init__(daemon=True)
        self.main_window = main_window
        self.hotkey_start_stop = keyboard.HotKey(keyboard.HotKey.parse('<ctrl>+<alt>+s'), self.on_start_stop)
        self.hotkey_pause_resume = keyboard.HotKey(keyboard.HotKey.parse('<ctrl>+<alt>+p'), self.on_pause_resume)

    def on_start_stop(self):
        # Safely trigger button clicks from this thread
        if self.main_window.worker:
            self.main_window.stop_button.click()
        else:
            self.main_window.start_button.click()

    def on_pause_resume(self):
        if self.main_window.worker:
            self.main_window.start_button.click()

    def run(self):
        with keyboard.Listener(
                on_press=self.for_canonical(self.hotkey_start_stop.press),
                on_release=self.for_canonical(self.hotkey_start_stop.release)
        ) as l, keyboard.Listener(
            on_press=self.for_canonical(self.hotkey_pause_resume.press),
            on_release=self.for_canonical(self.hotkey_pause_resume.release)
        ) as p:
            l.join()
            p.join()

    def for_canonical(self, f):
        return lambda k: f(self.main_window.hotkey_listener.canonical(k))


# =============================================================================
# MAIN WINDOW (GUI)
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... (Same __init__ content as before)
        self.setWindowTitle("Ghostwriter - Final Edition")
        self.setGeometry(100, 100, 1100, 800)
        self.setStyleSheet(DARK_STYLE)

        self.thread = None
        self.worker = None
        self.is_paused_state = False

        self._setup_ui()
        self._connect_signals()
        self.hotkey_listener = GlobalHotkeyListener(self)
        self.hotkey_listener.start()

    def _setup_ui(self):
        # ... (This is heavily expanded)
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        # Left Column: Text Input
        left_layout = QVBoxLayout()
        self.source_text_edit = QTextEdit()
        self.source_text_edit.setPlaceholderText("Paste your source text here...")
        left_layout.addWidget(QLabel("Source Text:"))
        left_layout.addWidget(self.source_text_edit)

        # Right Column: Controls
        right_layout = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        right_widget.setFixedWidth(400)

        # Title and Top Controls
        title_label = QLabel("Ghostwriter Controls");
        title_label.setObjectName("TitleLabel");
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        right_layout.addWidget(title_label)

        self.always_on_top_checkbox = QCheckBox("Always on Top")
        right_layout.addWidget(self.always_on_top_checkbox, 0, QtCore.Qt.AlignRight)

        # Profiles
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Typing Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(PROFILES.keys())
        profile_layout.addWidget(self.profile_combo)
        right_layout.addLayout(profile_layout)
        right_layout.addSpacing(10)

        # Main Actions
        actions_layout = QHBoxLayout()
        self.start_button = QPushButton("▶️ Start / Resume");
        self.start_button.setObjectName("StartButton")
        self.stop_button = QPushButton("🛑 Stop");
        self.stop_button.setObjectName("StopButton")
        actions_layout.addWidget(self.start_button);
        actions_layout.addWidget(self.stop_button)
        right_layout.addLayout(actions_layout)
        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)

        # Typing Cadence Group
        cadence_group = QGroupBox("Typing Cadence")
        cadence_layout = QVBoxLayout(cadence_group)
        self.duration_spinbox = self._create_slider_spinbox(cadence_layout, "Total Duration (min)", 1, 1440, 20,
                                                            is_spinbox=True)
        self.wpm_slider = self._create_slider_spinbox(cadence_layout, "Base WPM", 30, 150, 65)
        self.thinking_chance_slider = self._create_slider_spinbox(cadence_layout, "Thinking Pause %", 0, 50, 5)
        self.afk_chance_slider = self._create_slider_spinbox(cadence_layout, "AFK Break %", 0, 25, 2)
        right_layout.addWidget(cadence_group)

        # Error & Correction Group
        error_group = QGroupBox("Error & Correction")
        error_layout = QVBoxLayout(error_group)
        self.error_slider = self._create_slider_spinbox(error_layout, "Typo Rate %", 0, 20, 4)
        self.correction_delay_slider = self._create_slider_spinbox(error_layout, "Correction Delay %", 0, 100, 50)
        right_layout.addWidget(error_group)

        # AI Paraphrasing Group
        ai_group = QGroupBox("AI Paraphrasing (Gemini)")
        ai_layout = QVBoxLayout(ai_group)
        self.paraphrase_button = QPushButton("✨ Rewrite Text with AI")
        ai_layout.addWidget(self.paraphrase_button)
        self.intensity_combo = QComboBox();
        self.intensity_combo.addItems(["light", "moderate", "heavy"])
        intensity_layout = QHBoxLayout();
        intensity_layout.addWidget(QLabel("Intensity:"));
        intensity_layout.addWidget(self.intensity_combo)
        ai_layout.addLayout(intensity_layout)
        right_layout.addWidget(ai_group)

        # Log Console
        right_layout.addWidget(QLabel("<b>Log Console:</b>"))
        self.log_console = QTextEdit();
        self.log_console.setReadOnly(True)
        right_layout.addWidget(self.log_console)

        main_layout.addLayout(left_layout, 2)
        main_layout.addWidget(right_widget, 1)
        self.setCentralWidget(main_widget)
        self._apply_profile("The Careful Student")  # Set default profile

    def _create_slider_spinbox(self, layout, label, min_val, max_val, default_val, is_spinbox=False):
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel(label))
        widget_label = QLabel(str(default_val))
        if is_spinbox:
            widget = QSpinBox()
            widget.setRange(min_val, max_val)
            widget.setValue(default_val)
            widget.valueChanged.connect(lambda v: widget_label.setText(str(v)))  # This is just for show if needed
        else:
            widget = QSlider(QtCore.Qt.Horizontal)
            widget.setRange(min_val, max_val)
            widget.setValue(default_val)
            widget.valueChanged.connect(lambda v: widget_label.setText(str(v)))

        h_layout.addWidget(widget)
        h_layout.addWidget(widget_label)
        layout.addLayout(h_layout)
        return widget

    def _apply_profile(self, profile_name):
        profile = PROFILES.get(profile_name)
        if not profile: return  # Custom profile selected

        self.wpm_slider.setValue(profile['wpm'])
        self.error_slider.setValue(profile['error_rate'])
        self.correction_delay_slider.setValue(profile['correction_delay'])
        self.thinking_chance_slider.setValue(profile['thinking_chance'])
        self.afk_chance_slider.setValue(profile['afk_chance'])
        # You can also update spinboxes for durations if you add them to the UI
        self.log_message(f"Applied profile: {profile_name}")

    def _connect_signals(self):
        self.always_on_top_checkbox.toggled.connect(self.set_always_on_top)
        self.profile_combo.currentTextChanged.connect(self._apply_profile)
        self.start_button.clicked.connect(self.handle_start_resume)
        self.stop_button.clicked.connect(self.stop_all_processes)
        self.paraphrase_button.clicked.connect(self.start_paraphrasing)

    def set_always_on_top(self, checked):
        # This requires window recreation or flag setting.
        # The easy way:
        if checked:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowStaysOnTopHint)
        self.show()  # Re-show the window to apply the flag change

    def get_settings(self):
        return {
            "total_minutes": self.duration_spinbox.value(),
            "wpm": self.wpm_slider.value(),
            "error_rate": self.error_slider.value(),
            "correction_delay": self.correction_delay_slider.value(),
            "thinking_chance": self.thinking_chance_slider.value(),
            "thinking_duration": (2, 6),  # Could be made into sliders
            "afk_chance": self.afk_chance_slider.value(),
            "afk_duration": (30, 180)  # Could be made into sliders
        }

    def start_typing(self):
        source_text = self.source_text_edit.toPlainText()
        if not source_text.strip():
            self.log_message("⚠️ Cannot start typing: Text is empty.")
            return

        self._set_controls_enabled(False)
        self.start_button.setText("⏸️ Pause")
        self.is_paused_state = False
        self.log_console.clear()
        self.progress_bar.setValue(0)
        self.log_message("🚀 Starting Typing Process...")

        self.thread = QThread()
        self.worker = TypingWorker(source_text, self.get_settings())
        self.worker.moveToThread(self.thread)

        self.worker.signals.status_update.connect(self.log_message)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.finished.connect(self.on_process_finished)
        self.worker.signals.error.connect(self.on_process_error)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    # (All other methods like handle_start_resume, stop_all_processes, _set_controls_enabled, log_message, etc. are the same as the previous version)
    # Paste the full MainWindow methods here from the previous answer, they should work with minor/no changes
    def _set_controls_enabled(self, enabled):
        """Enable or disable UI controls to prevent changes during operation."""
        self.source_text_edit.setEnabled(enabled)
        self.paraphrase_button.setEnabled(enabled)
        self.profile_combo.setEnabled(enabled)
        for group_box in self.findChildren(QGroupBox):
            group_box.setEnabled(enabled)

        if enabled:
            self.start_button.setText("▶️ Start / Resume")
            self.is_paused_state = False

    def log_message(self, message):
        self.log_console.append(message)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def set_paraphrased_text(self, text):
        self.source_text_edit.setPlainText(text)

    def on_process_finished(self):
        self.log_message("✅ Process finished.")
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = None
        self.worker = None
        self._set_controls_enabled(True)

    def on_process_error(self, error_message):
        self.log_message(f"❌ ERROR: {error_message}")
        self.on_process_finished()

    def start_paraphrasing(self):
        source_text = self.source_text_edit.toPlainText()
        if not source_text.strip():
            self.log_message("⚠️ Cannot paraphrase: Source text is empty.")
            return

        self._set_controls_enabled(False)
        self.log_message("🚀 Starting AI Paraphrasing...")

        self.thread = QThread()
        self.worker = ParaphraseWorker(
            text=source_text,
            intensity=self.intensity_combo.currentText()
        )
        self.worker.moveToThread(self.thread)

        self.worker.signals.status_update.connect(self.log_message)
        self.worker.signals.paraphrased_text_ready.connect(self.set_paraphrased_text)
        self.worker.signals.finished.connect(self.on_process_finished)
        self.worker.signals.error.connect(self.on_process_error)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def handle_start_resume(self):
        if self.worker and self.is_paused_state:
            self.worker.engine.resume()
            self.start_button.setText("⏸️ Pause")
            self.is_paused_state = False
        elif self.worker and not self.is_paused_state:
            self.worker.engine.pause()
            self.start_button.setText("▶️ Resume")
            self.is_paused_state = True
        else:
            self.start_typing()

    def stop_all_processes(self):
        if self.worker and isinstance(self.worker, TypingWorker):
            self.worker.engine.stop()
            self.log_message("🛑 Sending stop signal...")

    def closeEvent(self, event):
        self.stop_all_processes()
        if self.thread:
            self.thread.quit()
            self.thread.wait(5000)
        event.accept()


# =============================================================================
# APPLICATION ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    msg_box = QtWidgets.QMessageBox()
    msg_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
    msg_box.setText("Ghostwriter Setup & Ethical Use")
    msg_box.setInformativeText(
        "Hotkeys have been enabled:\n"
        " • <Ctrl>+<Alt>+S: Start Typing / Stop\n"
        " • <Ctrl>+<Alt>+P: Pause / Resume\n\n"
        "Remember to use this tool responsibly and ethically."
    )
    msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
    msg_box.setStyleSheet("QLabel{min-width: 400px;}")
    msg_box.exec()
    window.show()
    sys.exit(app.exec())