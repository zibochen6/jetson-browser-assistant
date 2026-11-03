"""Record the actual desktop at its original speed, independently of browser lifetime."""
import os
import re
import shutil
import signal
import subprocess
from .config import desktop_env


class Recording:
    def __init__(self, folder, wide=False):
        self.folder = folder
        self.wide = wide
        self.process = None
        self.log = None

    def start(self):
        if not shutil.which('ffmpeg'):
            return 'ffmpeg is not installed; desktop recording is unavailable'
        env = desktop_env()
        width, height = 1920, 1080
        try:
            output = subprocess.check_output(['xrandr', '--current'], env=env, text=True, timeout=5)
            match = re.search(r'current (\d+) x (\d+)', output)
            if match:
                width, height = min(int(match[1]), 3840 if self.wide else 2560), min(int(match[2]), 1440)
        except (OSError, subprocess.SubprocessError):
            pass
        width, height = width // 2 * 2, height // 2 * 2
        self.log = (self.folder / 'recording.log').open('wb')
        self.process = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y',
            '-f', 'x11grab', '-framerate', '10', '-video_size', f'{width}x{height}', '-i', env['DISPLAY'] + '.0+0,0',
            '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast', '-crf', '25', '-pix_fmt', 'yuv420p',
            str(self.folder / 'desktop.mp4')], env=env, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log)
        return None

    def stop(self):
        if not self.process:
            return None
        if self.process.poll() is None:
            try:
                self.process.communicate(b'q\n', timeout=12)
            except subprocess.TimeoutExpired:
                self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        path = self.folder / 'desktop.mp4'
        if self.process.returncode or not path.exists() or path.stat().st_size < 1000:
            return 'Desktop recording failed; see recording.log'
        return None
