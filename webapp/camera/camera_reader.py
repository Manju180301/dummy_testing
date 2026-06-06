import os

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = \
    "loglevel;quiet|rtsp_transport;tcp"

devnull = os.open(os.devnull, os.O_WRONLY)
os.dup2(devnull, 2)

import cv2
import threading
import time
from queue import Queue
from .motion_detector import detect_motion

FRAME_QUEUE = Queue(maxsize=100)
class CameraReader(threading.Thread):
    def __init__(self, cam_id, rtsp_url):
        super().__init__(daemon=True)
        self.cam_id = cam_id
        self.rtsp_url = rtsp_url
        self.cap = cv2.VideoCapture(rtsp_url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.prev_gray = None
        self.latest_frame = None

    def run(self):
        FRAME_INTERVAL = 0.5   # ✅ 2 FPS
        last_capture = 0
        frame_count = 0
        while True:
            now = time.time()
           
            if now - last_capture < FRAME_INTERVAL:
                time.sleep(0.01)
                continue
            last_capture = now
            ret, frame = self.cap.read()
            if not ret:
                continue
            frame = cv2.resize(frame, (1280, 720))
            self.latest_frame = frame
            self.prev_gray, motion = detect_motion(self.prev_gray, frame)
            #print(f"Cam-{self.cam_id} at {time.strftime('%H:%M:%S ')}")
            if motion:
                print(f"Motion  -True {self.cam_id} {time.strftime('%H:%M:%S ')}")
                if not FRAME_QUEUE.full():
                    FRAME_QUEUE.put((self.cam_id, frame))
                continue
            #print(f"Motion  -False {self.cam_id} {time.strftime('%H:%M:%S ')}")
            
    def get_frame(self):
        return self.latest_frame