from ultralytics import YOLO

# Load YOLOv8 model
model = YOLO("yolov8n.pt")   # nano = fastest (good for CCTV)

PHONE_CLASS_ID = 67  # COCO: cell phone

def detect_phones_yolo(frame):
    results = model(frame, conf=0.15, iou=0.45, verbose=False)

    phones = []

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls == PHONE_CLASS_ID:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                phones.append([x1, y1, x2, y2])

    return phones
