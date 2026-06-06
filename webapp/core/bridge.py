from webapp.camera.camera_reader import FRAME_QUEUE
from webapp.ai.mp_queue import MP_FRAME_QUEUE

def bridge_frames():
    while True:
        cam_id, frame = FRAME_QUEUE.get()
        MP_FRAME_QUEUE.put((cam_id, frame))