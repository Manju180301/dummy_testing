
import time
import gc
import platform

def ai_worker(worker_id, mp_queue):
    
    if platform.system() == "Windows":
        import os
        import django

        os.environ.setdefault(
            "DJANGO_SETTINGS_MODULE",
            "humantracking_system.settings"
        )

        django.setup()
    
    from webapp.face_core import recognize_faces, update_capture_logic
    
    last_run = 0
    YOLO_INTERVAL = 0.3
    frame_id = 0

    while True:
        cam_id, frame = mp_queue.get()
        if frame is None:
            break

        frame_id += 1
        now = time.time()

        if now - last_run < YOLO_INTERVAL:
            del frame
            continue

        last_run = now
        
        detections, person_boxes = recognize_faces(cam_id, frame)
        update_capture_logic(cam_id, frame, detections, person_boxes)
        # print(f"[Worker {worker_id}] Processed frame {frame_id} from {cam_id} - Persons: {len(person_boxes)}, Detections: {len(detections)}")
        del frame

        if frame_id % 50 == 0:
            gc.collect()