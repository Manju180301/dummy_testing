import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "loglevel;error"

import cv2
import threading
import time
from ultralytics import YOLO
from webapp.face_core import recognize_faces, update_capture_logic,draw_live_labels
# from webapp.yolo_phone import detect_phones_yolo


# helmet_model = YOLO("ppe.pt") 

# ================= DRAW DISPLAY =================

def detect_motion(prev_frame, curr_frame, blur_size=(21,21), threshold=20, min_area=3000):

    pg = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    cg = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)

    pg = cv2.GaussianBlur(pg, blur_size, 0)
    cg = cv2.GaussianBlur(cg, blur_size, 0)

    delta = cv2.absdiff(pg, cg)

    thresh = cv2.threshold(delta, threshold, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    return any(cv2.contourArea(c) > min_area for c in contours)


class CameraWorker:
    def __init__(self, name: str, src):
        self.name = name
        self.cap = self._open_capture(src)
        self.frame = None
        self.prev_frame = None
        self.lock = threading.Lock()
        self.running = True

        self.frame_id = 0
        self.frame_time = 0
        self.last_processed_id = 0
        
        # 5 FBS
        self.last_process_time = 0
        self.process_interval = 0.2   # ✅ 5 FPS
        
        self.latest_detections = []

        threading.Thread(target=self._update, daemon=True).start()
        threading.Thread(target=self._motion_loop, daemon=True).start()

    # ================= OPEN CAMERA =================
    def _open_capture(self, src):
        if isinstance(src, int):
            return cv2.VideoCapture(src, cv2.CAP_DSHOW)
        return cv2.VideoCapture(src, cv2.CAP_FFMPEG)

    # ================= FRAME UPDATE =================
    def _update(self):

        while self.running:

            ok, f = self.cap.read()

            if not ok or f is None:
                time.sleep(0.1)
                continue

            with self.lock:
                self.prev_frame = None if self.frame is None else self.frame.copy()
                self.frame = f

                self.frame_id += 1 

    # ================= MOTION LOOP =================
    def _motion_loop(self):

        #print(f"[{self.name}] Camera started")

        # PHONE_FACE_THRESHOLD = 100

        while self.running:

            with self.lock:
                pf = None if self.prev_frame is None else self.prev_frame.copy()
                cf = None if self.frame is None else self.frame.copy()

                fid = self.frame_id # current frame id

            if pf is None or cf is None:
                time.sleep(0.1)
                continue


            # ================= MOTION CHECK =================
            start_time = time.time()
            motion = detect_motion(pf, cf)
            
            if not motion:
                #print(f"[{self.name}] No motion detected")
                time.sleep(0.5)
                continue
            
            # 5 FBS
            now_time = time.time()

            if now_time - self.last_process_time < self.process_interval:
                continue

            self.last_process_time = now_time
            
            # ✅ OLD STYLE PRINT (ADD HERE)
            #print(f"[PROCESS] {self.name} | Frame:{fid} | Time:{time.strftime('%H:%M:%S')} | {now_time:.2f}")

            #print(f"[MOTION] {self.name} | Frame: {fid} | Motion: {motion}")


            # print(f"[{self.name}] Motion detected → running detection")
            # ================= FRAME SKIP =================
            if self.last_processed_id != 0:
                skipped = fid - self.last_processed_id - 1
                if skipped > 0:
                    #print(f"[WARNING] {self.name} | Skipped Frames: {skipped}")
                    pass

            self.last_processed_id = fid
                                                                                                        
            frame = cf.copy()          # save image
            display_frame = cf.copy()  # live stream


            # ================= FACE DETECTION =================
            #print(f"[PREDICTION] {self.name} | Frame: {fid}")
            detections, person_boxes = recognize_faces(frame)
            
            with self.lock:
                 self.latest_detections = detections

            '''
            # ================= PHONE DETECTION =================
            phone_boxes = detect_phones_yolo(frame)


            for d in detections:

                fx1, fy1, fx2, fy2 = map(int, d["bbox"])
                fx, fy = (fx1 + fx2) // 2, (fy1 + fy2) // 2

                for pb in phone_boxes:

                    px1, py1, px2, py2 = map(int, pb)
                    px, py = (px1 + px2) // 2, (py1 + py2) // 2

                    dist = ((fx - px)**2 + (fy - py)**2) ** 0.5

                    if dist < PHONE_FACE_THRESHOLD:
                        d["phone_detected"] = True
                        d["phone_distance"] = round(dist, 2)
                        break


            # ================= HELMET DETECTION =================
            resized = cv2.resize(frame, (640, 480))

            helmet_results = helmet_model(
                resized,
                conf=0.3,
                imgsz=640,
                verbose=False
            )[0]


            helmet_boxes = []

            for box in helmet_results.boxes:

                cls = helmet_model.names[int(box.cls[0])].lower()

                if cls in ["helmet", "hardhat"]:
                    helmet_boxes.append(list(map(int, box.xyxy[0])))


            # ================= HELMET ASSIGN =================
            for d in detections:

                fx1, fy1, fx2, fy2 = map(int, d["bbox"])
                fcx, fcy = (fx1 + fx2) // 2, (fy1 + fy2) // 2

                helmet_found = False

                for hx1, hy1, hx2, hy2 in helmet_boxes:

                    hcx, hcy = (hx1 + hx2) // 2, (hy1 + hy2) // 2

                    dist = ((fcx - hcx)**2 + (fcy - hcy)**2) ** 0.5

                    if dist < 120:
                        helmet_found = True
                        break

                d["helmet_detected"] = helmet_found

            '''
            # ================= SAVE TO DATABASE =================
            update_capture_logic(self.name, frame, detections, person_boxes)

            # ================= EXACT DB LOG PRINT =================
            if len(detections) == 0:
                #print(f"[DB] {self.name} | Frame: {fid} | NO PERSON DETECTED")
                pass

            for i, d in enumerate(detections):

                # print(
                #     f"[DB] {self.name} | Frame: {fid} | Det {i} | "
                #     f"emp_id: {d['emp_id']} | "
                #     f"similarity_score: {d['similarity_score']} | "
                #     f"similarity_id: {d['similarity_id']}"
                # )
                pass
                
                
            end_time = time.time()
            total_ms = (end_time - start_time) * 1000

            #print(f"[TOTAL MS] {self.name} | Frame: {fid} | {total_ms:.1f} ms")


            #print("-" * 80)
            
            # 5 FBS
            #time.sleep(1)


    # ================= STREAM FRAME =================
    def get_jpeg(self):

        with self.lock:

            if self.frame is None:
                return None

            # ret, buf = cv2.imencode(".jpg", self.frame)
            
            frame = self.frame.copy()

            draw_live_labels(
                frame,
                self.latest_detections
            )

            ret, buf = cv2.imencode(".jpg", frame)

            return buf.tobytes() if ret else None


    # ================= STOP CAMERA =================
    def stop(self):

        self.running = False

        self.cap.release()

        print(f"[{self.name}] Camera stopped")


# ================= MAIN =================
if __name__ == "__main__":

    try:

        while True:
            time.sleep(0.2)

    except KeyboardInterrupt:

        print("Exited cleanly.")