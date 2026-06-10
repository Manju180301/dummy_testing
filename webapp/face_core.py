import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from django.conf import settings
from ultralytics import YOLO

# ================= CONFIG =================
GALLERY_FILE = "Texa_employees_emb.npz"

# BASE_DIR = Path(__file__).resolve().parent.parent
# GALLERY_FILE = BASE_DIR / "output_emp.npz"

MATCH_THRESHOLD = 0.47
SIMILAR_THRESHOLD = 0.25
CAPTURE_INTERVAL = 10 * 60   

import platform   

DATA_ROOT = "recognized_cctv"

if platform.system() == "Windows":
    SAVE_DIR = Path(settings.BASE_DIR) / DATA_ROOT
else:
    SAVE_DIR = Path(settings.MEDIA_ROOT) / DATA_ROOT

SAVE_DIR.mkdir(exist_ok=True)

# ================= GLOBALS =================
app = None
gallery = None

last_capture_time = {}

yolo_person = YOLO("yolov8n.pt")
#yolo_person.to("cuda")  

def detect_person_boxes(image):
    #print(f"[YOLO GPU] Device: {yolo_person.device}")  # 🔥 ADD
    result = yolo_person(image, classes=[0], conf=0.4, verbose=False)[0]
    boxes = []
    for b in result.boxes:
        boxes.append(tuple(map(int, b.xyxy[0])))
    return boxes

# ================= DJANGO MODEL =================
def get_recognized_model():
    from webapp.models import RecognizedFace
    return RecognizedFace


def get_face_app():
    global app
    if app is None:
        import insightface
        app = insightface.app.FaceAnalysis(name="buffalo_l")
        app.prepare(ctx_id=0, det_size=(640, 640))
    return app


# ================= LOAD GALLERY =================
def load_gallery():
    global gallery
    if gallery is None:
        data = np.load(GALLERY_FILE, allow_pickle=True)
        gallery = {k: data[k].astype(np.float32) for k in data.files}
        print("📚 Gallery loaded:", list(gallery.keys()))

get_face_app()
load_gallery()

def recognize_faces(image):
    detections = []

    # STEP 1: Detect persons FIRST
    person_boxes = detect_person_boxes(image)

    #  NO PERSON → DO NOTHING
    if len(person_boxes) == 0:
        return [], [] 

     
    # if len(person_boxes) == 0:
    #     return [], []

    #  STEP 2: Detect faces
    faces = app.get(image)
    
    valid_faces = faces

    #  STEP 4: MATCH PERSON ↔ FACE
    for (px1, py1, px2, py2) in person_boxes:

        has_face = False

        for face in valid_faces:
            fx1, fy1, fx2, fy2 = face.bbox

            # ✅ check if face inside person
            fcx = (fx1 + fx2) // 2
            fcy = (fy1 + fy2) // 2

            if px1 <= fcx <= px2 and py1 <= fcy <= py2:
                has_face = True

                emb = face.normed_embedding.astype(np.float32)

                best_score = -1.0
                best_id = None

                for emp_id, g_emb in gallery.items():
                    score = float(np.dot(emb, g_emb))
                    if score > best_score:
                        best_score = score
                        best_id = emp_id

                # ================= CLASSIFICATION =================
                if best_score >= MATCH_THRESHOLD:
                    emp_id = best_id
                    similarity_id = None
                    folder = emp_id
                    label = emp_id 

                elif SIMILAR_THRESHOLD <= best_score < MATCH_THRESHOLD:
                    emp_id = None
                    similarity_id = best_id
                    folder = f"similarity/{best_id}"
                    label = best_id

                else:
                    emp_id = None
                    similarity_id = "UNKNOWN"
                    folder = "unknown"
                    label = "unknown"

                detections.append({
                    "emp_id": emp_id,
                    "similarity_id": similarity_id,
                    "similarity_score": round(best_score, 2),
                    "bbox": [fx1, fy1, fx2, fy2],  # face box
                    "person_bbox": [px1, py1, px2, py2],  #person box
                    "folder": folder,
                    "label": label,
                    "person_key": label,
                    "phone_detected": False,
                    "phone_distance": None,
                    "helmet_detected": False
                })

                break

        #  NO FACE FOR THIS PERSON → NO_FACE
        if not has_face:
            detections.append({
                "emp_id": None,
                "similarity_id": "NO_FACE",
                "similarity_score": 0.0,
                "bbox": [px1, py1, px2, py2],  #save crop box
                "person_bbox": [px1, py1, px2, py2], # person box 
                "folder": "no_face",
                "label": "no_face",
                "person_key": "NO_FACE",
                "phone_detected": False,
                "phone_distance": None,
                "helmet_detected": False
            })

    return detections, person_boxes 


# ================= SAVE IMAGE + DB =================
def save_capture(camera_name, image, det):
    x1, y1, x2, y2 = map(int, det["bbox"])
    h, w = image.shape[:2]

    #  ONLY CHANGE FOR NO_FACE
    if det["label"] == "no_face":
        x1, y1, x2, y2 = map(int, det["bbox"])

        # 🔥 HEIGHT REDUCE (KEEP TOP PART ONLY)
        h_box = y2 - y1
        y2 = y1 + int(h_box * 0.6)   # keep top 60%

    else:
        # 👉 Keep your original logic for face
        pad = 2.0
        bw = int((x2 - x1) * pad)
        bh = int((y2 - y1) * pad)

        x1 = max(0, x1 - bw)
        y1 = max(0, y1 - bh)
        x2 = min(w, x2 + bw)
        y2 = min(h, y2 + bh)

        # reduce top only
        y1 += int((y2 - y1) * 0.1)

    face = image[y1:y2, x1:x2]
    if face.size == 0:
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = SAVE_DIR / camera_name / det["folder"]
    out_dir.mkdir(parents=True, exist_ok=True)
     
    # ================= SAVE IMAGE =================

    img_path = out_dir / f"{det['label']}_{ts}.jpg"
    cv2.imwrite(str(img_path), face)

    if platform.system() == "Windows":
        db_path = f"{camera_name}/{det['folder']}/{img_path.name}"
    else:
        db_path = f"{DATA_ROOT}/{camera_name}/{det['folder']}/{img_path.name}"

    try:
        RecognizedFace = get_recognized_model()
        
        RecognizedFace.objects.create(
            camera_name=camera_name,
            emp_id=det["emp_id"],
            similarity_id=det["similarity_id"],
            similarity_score=det["similarity_score"],
            image_path=db_path,
            phone_detected=det.get("phone_detected", False),
            phone_distance=det.get("phone_distance"),
            bbox=list(map(int, det["bbox"])),
            helmet_detected=det.get("helmet_detected", False)
        )
        

    except Exception as e:
        print("❌ Failed to save to DB:", e)
    
def draw_live_labels(frame, detections):

    import cv2

    for det in detections:

        if "person_bbox" in det:
            x1, y1, x2, y2 = map(int, det["person_bbox"])

            # shrink huge YOLO box
            pad_w = int((x2 - x1) * 0.15)
            pad_h = int((y2 - y1) * 0.10)

            x1 += pad_w
            x2 -= pad_w
            y1 += pad_h
            y2 -= pad_h

        else:
            x1, y1, x2, y2 = map(int, det["bbox"])

        if det["emp_id"]:
            color = (0, 255, 0)      # Green
            label = det["emp_id"]

        elif det["similarity_id"] == "UNKNOWN":
            color = (0, 0, 255)      # Red
            label = "UNKNOWN"

        elif det["similarity_id"] == "NO_FACE":
            color = (255, 0, 0)      # Blue
            label = "NO_FACE"

        else:
            continue

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        cv2.putText(
            frame,
            label,
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255) ,   # Black text
            3
        )

    return frame

# ================= CAPTURE LOGIC (FINAL) =================        
            
last_capture_time = {}   
last_camera = {}         

last_unknown_capture = {}
last_noface_capture = {}

UNKNOWN_INTERVAL = 180   # 3 min
NOFACE_INTERVAL = 120    # 2 min

# ================= CAPTURE LOGIC (FINAL) =================
def update_capture_logic(camera_name, image, detections, person_boxes):

    now = datetime.now()
    
    for det in detections:
        
        # print(
        #     f"[{datetime.now().strftime('%H:%M:%S')}] "
        #     f"SAVE CHECK -> "
        #     f"camera={camera_name} "
        #     f"emp_id={det['emp_id']} "
        #     f"similarity_id={det['similarity_id']} "
        #     f"score={det['similarity_score']}"
        # )
        
        # if det["label"] == "no_face":
        #   continue   # ❌ skip no_face completely

        emp_id = det["emp_id"]
        # if emp_id is None:
        #     continue
        
        # ======================================
        # NO_FACE -> 120 sec
        # ======================================
        if det["similarity_id"] == "NO_FACE":

            key = (camera_name, "NO_FACE")
            last = last_noface_capture.get(key)

            if last is None or (now - last).total_seconds() >= NOFACE_INTERVAL:
                save_capture(camera_name, image, det)
                last_noface_capture[key] = now

            continue


        # ======================================
        # UNKNOWN -> 180 sec
        # ======================================
        if det["similarity_id"] == "UNKNOWN":

            key = (camera_name, "UNKNOWN")
            last = last_unknown_capture.get(key)

            if last is None or (now - last).total_seconds() >= UNKNOWN_INTERVAL:
                save_capture(camera_name, image, det)
                last_unknown_capture[key] = now

            continue


        # ======================================
        # SIMILARITY -> SAVE EVERY TIME
        # ======================================
        if emp_id is None and det["similarity_id"] not in ["UNKNOWN", "NO_FACE"]:

            save_capture(camera_name, image, det)
            continue


        # -------- KEY STATE ----------
        key = (emp_id, camera_name)

        last_time = last_capture_time.get(key)
        last_cam  = last_camera.get(emp_id)


        # =================================================
        # 📱 PHONE DETECT → PRIORITY CAPTURE
        # =================================================
        # if det.get("phone_detected"):

        #     if last_time is None:
        #         save_capture(camera_name, image, det)
        #         last_capture_time[key] = now
        #         last_camera[emp_id] = camera_name
        #         continue

        #     #10 mints logic 

        #     diff = (now - last_time).total_seconds()

        #     if diff >= CAPTURE_INTERVAL:
        #         save_capture(camera_name, image, det)
        #         last_capture_time[key] = now
        #         last_camera[emp_id] = camera_name

        #     ##without 10 mints logic

        #     # save_capture(camera_name, image, det)
        #     # last_capture_time[key] = now
        #     # last_camera[emp_id] = camera_name

        #     continue


        # =================================================
        # FIRST TIME EVER
        # =================================================
        if last_cam is None:
            save_capture(camera_name, image, det)
            last_capture_time[key] = now
            last_camera[emp_id] = camera_name
            continue


        # =================================================
        # CAMERA CHANGED
        # =================================================
        if last_cam != camera_name:
            save_capture(camera_name, image, det)
            last_capture_time[key] = now
            last_camera[emp_id] = camera_name
            continue


        # =================================================
        # SAME CAMERA → INTERVAL CHECK
        # =================================================
        if last_time is None:
            save_capture(camera_name, image, det)
            last_capture_time[key] = now
            continue


        # diff = (now - last_time).total_seconds()

        # if diff >= CAPTURE_INTERVAL:
        #     save_capture(camera_name, image, det)
        #     last_capture_time[key] = now

        #without 10 mints logic

        save_capture(camera_name, image, det)
        last_capture_time[key] = now



