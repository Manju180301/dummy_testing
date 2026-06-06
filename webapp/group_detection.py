# webapp/group_detection.py
import cv2
import numpy as np
from ultralytics import YOLO
from sklearn.cluster import DBSCAN
from datetime import datetime


USE_SEPARATE_MODEL = False
GROUP_DETECTION_MODEL = "yolov8m-pose.pt"
AVG_PERSON_HEIGHT = 1.7                     # meters
FOCAL_LENGTH = 700                          # pixels

CONFIDENCE_THRESHOLD = 0.35
MIN_PERSON_WIDTH = 30
MIN_PERSON_HEIGHT = 50


# Group Detection Settings
TOP_ANCHOR_RATIO = 0.15                     # 15% down from top
ENABLE_4_SECTION_GRID = True                # Divide camera into 4 sections
SHOW_GRID_LINES = True                      # Show section boundaries


# Display Settings
SHOW_TOP_ANCHOR = True
SHOW_DISTANCE_LINES = True


# Frame Processing Settings
USE_FRAME_INTERVAL = True
FRAME_INTERVAL_SECONDS = 2                  


# Alert Settings 
THRESHOLD_PERCENT = 100                     

# Load YOLO model
if USE_SEPARATE_MODEL:
    #print(f"🔄 Loading YOLO model: {GROUP_DETECTION_MODEL}")
    try:
        model = YOLO(GROUP_DETECTION_MODEL)
        IS_POSE_MODEL = "pose" in GROUP_DETECTION_MODEL.lower()
        #print(f"✅ Model loaded: {GROUP_DETECTION_MODEL}")
        if IS_POSE_MODEL:
            print(f"   Pose model detected - will use keypoints for accurate detection")
        else:
            print(f"   Standard detection model - will use bounding box only")
    except Exception as e:
        # print(f"❌ Failed to load {GROUP_DETECTION_MODEL}: {e}")
        # print("🔄 Falling back to yolov8n.pt")
        model = YOLO("yolov8n.pt")
        IS_POSE_MODEL = False
else:
    try:
        from webapp.face_core import yolo_person as shared_model
        model = shared_model
        IS_POSE_MODEL = False
        # print("✅ Using shared model from face_core.py")
    except ImportError:
        model = YOLO("yolov8n.pt")
        IS_POSE_MODEL = False
        # print("✅ Using default yolov8n.pt model")


def estimate_distance_from_person(box_height_px):
    """Estimate distance from camera based on bounding box height"""
    if box_height_px <= 0:
        return 99.9
    return round((AVG_PERSON_HEIGHT * FOCAL_LENGTH) / box_height_px, 2)


def get_section_id(x, y, w, h):
    """Determine which section (1-4) a point belongs to"""
    if not ENABLE_4_SECTION_GRID:
        return 0
    section_w = w // 2
    section_h = h // 2
    col = 0 if x < section_w else 1
    row = 0 if y < section_h else 1
    return row * 2 + col


def extract_keypoints(result):
    keypoints_list = []
    if result.keypoints is not None:
        kpts = result.keypoints.data.cpu().numpy()
        for kp in kpts:
            person_keypoints = []
            for i in range(len(kp)):
                if kp[i][2] > 0.5:  # confidence threshold
                    person_keypoints.append((int(kp[i][0]), int(kp[i][1])))
                else:
                    person_keypoints.append(None)
            keypoints_list.append(person_keypoints)
    return keypoints_list


def get_head_position(keypoints):
    """Get head/nose position from pose keypoints (keypoint 0 = nose)"""
    if not keypoints or len(keypoints) < 1:
        return None
    return keypoints[0] if keypoints[0] else None


def get_neck_position(keypoints):
    """Get neck position from shoulder keypoints"""
    if not keypoints or len(keypoints) < 7:
        return None
    left_shoulder = keypoints[5] if len(keypoints) > 5 else None
    right_shoulder = keypoints[6] if len(keypoints) > 6 else None
    if left_shoulder and right_shoulder:
        neck_x = (left_shoulder[0] + right_shoulder[0]) // 2
        neck_y = (left_shoulder[1] + right_shoulder[1]) // 2
        return (neck_x, neck_y)
    return None


def get_measurement_point(bbox, keypoints=None):
    """Get the optimal measurement point based on available data"""
    x1, y1, x2, y2 = bbox
    height = y2 - y1
    
    # For pose models, use head/nose keypoint for better accuracy
    if IS_POSE_MODEL and keypoints:
        head = get_head_position(keypoints)
        if head:
            return head
        neck = get_neck_position(keypoints)
        if neck:
            return neck
    
    # Fallback to bounding box top
    top_x = (x1 + x2) // 2
    top_y = y1 + int(height * TOP_ANCHOR_RATIO)
    return (top_x, top_y)


def detect_persons(frame):
    """Detect persons in frame using selected model"""
    results = model(frame, classes=[0], conf=CONFIDENCE_THRESHOLD, verbose=False)[0]
    persons = []
    
    # Extract keypoints if using pose model
    keypoints_list = extract_keypoints(results) if IS_POSE_MODEL else []
    
    for idx, box in enumerate(results.boxes):
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        w = x2 - x1
        h = y2 - y1
        if w >= MIN_PERSON_WIDTH and h >= MIN_PERSON_HEIGHT:
            person_keypoints = keypoints_list[idx] if IS_POSE_MODEL and idx < len(keypoints_list) else []
            persons.append({
                'bbox': (x1, y1, x2, y2),
                'keypoints': person_keypoints
            })
    
    return persons


def compute_real_distance(point1, point2, dist_cam1, dist_cam2):
    """Calculate real distance between two points in meters"""
    if not point1 or not point2:
        return 999.0
    pixel_dist = np.hypot(point1[0] - point2[0], point1[1] - point2[1])
    avg_cam_dist = (dist_cam1 + dist_cam2) / 2.0
    if avg_cam_dist <= 0:
        return 999.0
    return round((pixel_dist * avg_cam_dist) / FOCAL_LENGTH, 2)


def detect_groups(frame, eps=1.0, min_samples=2, alert_min_size=None, camera_name=None):
    """
    Detect groups in frame. Automatically uses pose model if available.
    """
    if frame is None:
        return [], frame, []

    h, w = frame.shape[:2]
    raw_persons = detect_persons(frame)

    annotated = frame.copy()
    
    # Draw grid sections
    if ENABLE_4_SECTION_GRID and SHOW_GRID_LINES:
        half_w = w // 2
        half_h = h // 2
        cv2.line(annotated, (half_w, 0), (half_w, h), (255, 255, 255), 2)
        cv2.line(annotated, (0, half_h), (w, half_h), (255, 255, 255), 2)
        cv2.putText(annotated, "Section 1", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(annotated, "Section 2", (half_w + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(annotated, "Section 3", (10, half_h + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(annotated, "Section 4", (half_w + 10, half_h + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
    
    all_persons = []
    for idx, person in enumerate(raw_persons, start=1):
        x1, y1, x2, y2 = person['bbox']
        height = y2 - y1
        distance = estimate_distance_from_person(height)
        
        # Get measurement point (uses keypoints for pose models)
        measure_point = get_measurement_point(person['bbox'], person.get('keypoints', []))
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        section = get_section_id(measure_point[0], measure_point[1], w, h) if measure_point else 0
        
        all_persons.append({
            'id': idx,
            'bbox': (x1, y1, x2, y2),
            'measure_point': measure_point,
            'center': (center_x, center_y),
            'distance': distance,
            'section': section,
            'in_alert_group': False,
            'keypoints': person.get('keypoints', [])
        })
    
    # Detect groups using DBSCAN
    groups = []
    threshold = alert_min_size if alert_min_size is not None else min_samples
    
    for section_id in range(4):
        section_persons = [p for p in all_persons if p['section'] == section_id]
        if len(section_persons) < min_samples:
            continue
        
        n = len(section_persons)
        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i+1, n):
                if section_persons[i]['measure_point'] and section_persons[j]['measure_point']:
                    d = compute_real_distance(
                        section_persons[i]['measure_point'],
                        section_persons[j]['measure_point'],
                        section_persons[i]['distance'],
                        section_persons[j]['distance']
                    )
                    dist_matrix[i, j] = d
                    dist_matrix[j, i] = d
                else:
                    dist_matrix[i, j] = 999
                    dist_matrix[j, i] = 999
        
        clustering = DBSCAN(eps=eps, min_samples=min_samples, metric='precomputed')
        labels = clustering.fit_predict(dist_matrix)
        
        for lbl in set(labels):
            if lbl == -1:
                continue
            member_indices = [i for i, l in enumerate(labels) if l == lbl]
            if len(member_indices) < min_samples:
                continue
            
            group_size = len(member_indices)
            member_boxes = [section_persons[i]['bbox'] for i in member_indices]
            gx1 = min(b[0] for b in member_boxes)
            gy1 = min(b[1] for b in member_boxes)
            gx2 = max(b[2] for b in member_boxes)
            gy2 = max(b[3] for b in member_boxes)
            
            groups.append({
                'size': group_size,
                'box': (gx1, gy1, gx2, gy2),
                'member_ids': [section_persons[i]['id'] for i in member_indices],
                'section': section_id
            })
            
            if group_size >= threshold:
                for idx in member_indices:
                    for p in all_persons:
                        if p['id'] == section_persons[idx]['id']:
                            p['in_alert_group'] = True
                            break
                
                model_type = "POSE" if IS_POSE_MODEL else "STANDARD"
                #print(f"[GROUP] {model_type} - Section {section_id+1}: {group_size} people (IDs {groups[-1]['member_ids']})")
    
    alert_groups = [g for g in groups if g['size'] >= threshold]
    alert_persons = [p for p in all_persons if p['in_alert_group']]
    
    if alert_groups:
        #print(f"\n⚠️ ALERT SUMMARY: {len(alert_groups)} group(s) exceeded threshold (min {threshold} people)")
        for g in alert_groups:
            #print(f"   - Section {g['section']+1}: {g['size']} people (IDs {g['member_ids']})")
            pass
    
    return groups, annotated, alert_persons


def draw_annotations(frame, persons, groups, threshold):
    if frame is None:
        return None
    
    annotated = frame.copy()
    h, w = annotated.shape[:2]
    
    # ========== 1. DRAW ALL PERSONS ==========
    for p in persons:
        x1, y1, x2, y2 = p['bbox']
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # Get measurement point (head area)
        measure_point = p.get('measure_point')
        if not measure_point:
            top_x = (x1 + x2) // 2
            top_y = y1 + int((y2 - y1) * TOP_ANCHOR_RATIO)
            measure_point = (top_x, top_y)
        
        # Draw green circle at person's center
        cv2.circle(annotated, (center_x, center_y), 15, (0, 255, 0), 2)
        cv2.circle(annotated, (center_x, center_y), 3, (0, 255, 0), -1)
        
        # Draw measurement point marker
        marker_color = (0, 255, 255) if IS_POSE_MODEL else (255, 255, 0)
        cv2.circle(annotated, measure_point, 8, marker_color, 2)
        cv2.circle(annotated, measure_point, 2, marker_color, -1)
        
        # Draw bounding box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        
        # Draw person label
        distance_m = p.get('distance', 0)
        model_tag = "POSE" if IS_POSE_MODEL else "YOLO"
        label = f"P{p['id']} | {distance_m:.2f}m | {model_tag}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 2)
        cv2.rectangle(annotated, (x1, y1-25), (x1+tw+10, y1-5), (0, 0, 0), -1)
        cv2.putText(annotated, label, (x1+5, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 2)
        
        # Store point for group distance
        p['top_point'] = measure_point
    
    # ========== 2. DRAW ALL GROUPS ==========
    for g in groups:
        gx1, gy1, gx2, gy2 = g['box']
        # Expand the box slightly
        gx1 = max(0, gx1 - 10)
        gy1 = max(0, gy1 - 35)
        gx2 = min(w, gx2 + 10)
        gy2 = min(h, gy2 + 10)
        
        # Determine if this is an alert group
        is_alert = g['size'] >= threshold
        
        # Set box color
        if is_alert:
            color = (0, 0, 255)  # Red for alert groups
            line_thickness = 3
        else:
            color = (0, 200, 0)  # Green for normal groups
            line_thickness = 2
        
        cv2.rectangle(annotated, (gx1, gy1), (gx2, gy2), color, line_thickness)
        
        # Draw group label with proper text
        if is_alert:
            label = f"ALERT GROUP: {g['size']} people"
            text_color = (0, 0, 255)  # Red text for alert
        else:
            label = f"GROUP: {g['size']} people"
            text_color = (200, 200, 200)  # Light gray for normal
        
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        
        # Draw background rectangle for text
        cv2.rectangle(annotated, (gx1, gy1-30), (gx1+tw+10, gy1-5), (0, 0, 0), -1)
        cv2.putText(annotated, label, (gx1+5, gy1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 2)
        
        # Draw distance lines between group members
        if len(g['member_ids']) >= 2 and SHOW_DISTANCE_LINES:
            member_points = []
            member_distances = []
            for mid in g['member_ids']:
                for p in persons:
                    if p['id'] == mid:
                        pt = p.get('top_point')
                        if pt:
                            member_points.append(pt)
                            member_distances.append(p.get('distance', 0))
                        break
            
            # Draw lines between all pairs
            for i in range(len(member_points)):
                for j in range(i + 1, len(member_points)):
                    cv2.line(annotated, member_points[i], member_points[j], (0, 255, 255), 2)
                    
                    # Calculate real distance
                    dist_m = compute_real_distance(
                        member_points[i], member_points[j],
                        member_distances[i], member_distances[j]
                    )
                    
                    # Calculate midpoint for label
                    mx = (member_points[i][0] + member_points[j][0]) // 2
                    my = (member_points[i][1] + member_points[j][1]) // 2
                    
                    # Draw distance label
                    dist_label = f"{dist_m:.2f}m"
                    (tw, th), _ = cv2.getTextSize(dist_label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 2)
                    cv2.rectangle(annotated, (mx - tw//2 - 3, my - th - 3),
                                 (mx + tw//2 + 3, my + 3), (0, 0, 0), -1)
                    cv2.putText(annotated, dist_label, (mx - tw//2, my - 5),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 2)
    
    # ========== 3. STATISTICS OVERLAY ==========
    overlay = annotated.copy()
    cv2.rectangle(overlay, (10, 10), (370, 140), (0, 0, 0), -1)
    annotated = cv2.addWeighted(overlay, 0.6, annotated, 0.4, 0)
    
    total_people = len(persons)
    total_groups = len(groups)
    alert_groups = sum(1 for g in groups if g['size'] >= threshold)
    
    model_display = "YOLO-POSE" if IS_POSE_MODEL else "YOLO-STANDARD"
    cv2.putText(annotated, f"Model: {model_display}", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    cv2.putText(annotated, f"People Detected: {total_people}", (20, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(annotated, f"Groups Found: {total_groups}", (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(annotated, f"Alert Groups: {alert_groups}", (20, 95),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    point_type = "KEYPOINT" if IS_POSE_MODEL else "HEAD_ANCHOR"
    cv2.putText(annotated, f"Distance Point: {point_type}", (20, 115),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    
    # Add alert message if there are alert groups
    if alert_groups > 0:
        cv2.putText(annotated, "!!! ALERT: Overcrowding Detected !!!", (w - 400, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    return annotated
