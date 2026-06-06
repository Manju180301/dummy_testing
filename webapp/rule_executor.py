from webapp.models import Rule, Employee, RecognizedFace,CameraBoundary
import math
from collections import defaultdict
from datetime import datetime, timedelta
from webapp.face_core import save_full_frame

from datetime import datetime, time
from webapp import views
import os

#---------------MEETING RULE-------------------
from webapp.mailer import send_meeting_alert

LAST_ALERT_SENT = {}
LAST_MISSING_STATE = defaultdict(set)  

def execute_meeting_rules():

    now = datetime.now()
    today = now.date()
    current_time = now.time()

    try:
        rule_obj = Rule.objects.get(rule_type="meeting")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():

        if not rule.get("active", False):
            continue

        rule_date = datetime.strptime(rule["date"], "%Y-%m-%d").date()
        if rule_date != today:
            continue

        start_time = datetime.strptime(rule["start_time"], "%H:%M").time()
        end_time   = datetime.strptime(rule["end_time"], "%H:%M").time()

        # Outside meeting time
        if not (start_time <= current_time <= end_time):

            # After meeting ends → reset state
            if current_time > end_time:
                LAST_MISSING_STATE.pop(rule_key, None)
                LAST_ALERT_SENT.pop(rule_key, None)

            continue

        # ✅ Directly call process (NO throttle here)
        process_meeting_rule(rule, rule_key, today, now)
        

def process_meeting_rule(rule, rule_key, today, now):

    departments = rule.get("department", [])
    camera_names = rule["place"]
    head_email   = rule["head_email"]

    # ------------------------------
    # STEP 1 — Total Dept Employees
    # ------------------------------
    dept_employee_ids = set(
        Employee.objects.filter(
            dept__in=departments
        ).values_list("emp_id", flat=True)
    )

    if not dept_employee_ids:
        return

    total_employees = len(dept_employee_ids)

    # ------------------------------
    # STEP 2 — Present in Meeting Room
    # ------------------------------
    meeting_start = datetime.combine(
        today,
        datetime.strptime(rule["start_time"], "%H:%M").time()
    )

    present_ids = set(
        RecognizedFace.objects.filter(
            camera_name__in=camera_names,
            capture_date_time__range=(meeting_start, now),
            emp_id__in=dept_employee_ids
        )
        .exclude(emp_id__in=["", "UNKNOWN", "NO_FACE"])
        .values_list("emp_id", flat=True)
        .distinct()
    )

    present_count = len(present_ids)

    # ------------------------------
    # STEP 3 — Missing
    # ------------------------------
    missing_ids = dept_employee_ids - present_ids
    current_missing_set = set(missing_ids)

    previous_missing = LAST_MISSING_STATE.get(rule_key, set())
    last_sent = LAST_ALERT_SENT.get(rule_key)

    # ------------------------------
    # STEP 4 — Stable 3-Minute Logic
    # ------------------------------
    should_send = False

    if current_missing_set:

        # Missing list changed
        if current_missing_set != previous_missing:
            should_send = True

        # Same missing but 3 minutes passed
        elif last_sent and (now - last_sent).total_seconds() >= 180:
            should_send = True

    # ------------------------------
    # STEP 5 — Send Alert
    # ------------------------------
    if should_send:

        image_path = None

        # 🔥 Find newly entered employees
        newly_entered = present_ids - previous_missing

        # If someone newly entered → use that image
        if newly_entered:
            latest_emp = list(newly_entered)[0]

            latest_record = (
                RecognizedFace.objects
                .filter(emp_id=latest_emp, camera_name__in=camera_names)
                .order_by("-capture_date_time")
                .first()
            )

            if latest_record and latest_record.image_path:
                image_path = latest_record.image_path
                #print("✅ Using NEW employee image:", image_path)

        # If no new entry (3-min reminder)
        elif present_ids:
            latest_emp = list(present_ids)[0]

            latest_record = (
                RecognizedFace.objects
                .filter(emp_id=latest_emp, camera_name__in=camera_names)
                .order_by("-capture_date_time")
                .first()
            )

            if latest_record and latest_record.image_path:
                image_path = latest_record.image_path
                print("✅ Using existing employee image:", image_path)

        # ------------------------------
        # Missing Employee Details
        # ------------------------------
        missing_employees = Employee.objects.filter(
            emp_id__in=missing_ids
        ).values_list("emp_id", "emp_name")

        missing_list = [
            f"{eid} - {name}" for eid, name in missing_employees
        ]

        send_meeting_alert(
            to_email=head_email,
            place=", ".join(camera_names),
            start_time=rule["start_time"],
            end_time=rule["end_time"],
            total=total_employees,
            present=present_count,
            missing=missing_list,
            image_path=image_path
        )

        LAST_MISSING_STATE[rule_key] = current_missing_set
        LAST_ALERT_SENT[rule_key] = now

    # ------------------------------
    # If everyone present → reset state
    # ------------------------------
    elif not current_missing_set and previous_missing:
        LAST_MISSING_STATE[rule_key] = set()
        
        

#-----------------ALLOWED PLACE RULE-------------
from webapp.mailer import send_allowed_place_alert
from webapp.face_core import UNKNOWN_INTERVAL

ALLOWED_PLACE_LAST_ALERT = {}

def execute_allowed_place_rules():
    now = datetime.now()

    try:
        rule_obj = Rule.objects.get(rule_type="allowed_place")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():
        zone_type = rule.get("zone_type","Zone")
        if rule.get("time_mode") == "custom":
            now_time = now.time()

            start = datetime.strptime(rule["start_time"], "%H:%M").time()
            end = datetime.strptime(rule["end_time"], "%H:%M").time()

            if not (start <= now_time <= end):
                continue

        if not rule.get("active", False):
            continue

        allowed_departments= rule.get("department", [])
        camera_names = rule["place"]
        head_email = rule["head_email"]

        recent_start = now - timedelta(minutes=1)

        records = (
            RecognizedFace.objects
            .filter(
                camera_name__in=camera_names,
                capture_date_time__gte=recent_start
            )
            .order_by("-capture_date_time")
        )

        if not records.exists():
            continue

        for rec in records:

            emp = Employee.objects.filter(emp_id=rec.emp_id).first()

            # ---------------- EMPLOYEE CASE ----------------
            if rec.emp_id and emp:

                if emp.dept not in allowed_departments:

                    send_allowed_place_alert(
                        to_email=head_email,
                        emp_id=emp.emp_id,
                        emp_name=emp.emp_name,
                        emp_dept=emp.dept,
                        allowed_dept=allowed_departments,
                        place=rec.camera_name,
                        time_str=rec.capture_date_time.strftime("%H:%M:%S"),
                        image_path=rec.image_path,
                        zone_type=zone_type
                    )

                    ALLOWED_PLACE_LAST_ALERT[rule_key] = now
                    continue

            # ---------------- UNKNOWN PERSON ----------------
            if not rec.emp_id and rec.similarity_id:

                last_alert = ALLOWED_PLACE_LAST_ALERT.get(rule_key)

                if last_alert:
                    diff = (now - last_alert).total_seconds()

                    if diff < UNKNOWN_INTERVAL:
                        continue

                send_allowed_place_alert(
                    to_email=head_email,
                    emp_id=None,
                    emp_name=None,
                    emp_dept=None,
                    allowed_dept=allowed_departments,
                    place=rec.camera_name,
                    time_str=rec.capture_date_time.strftime("%H:%M:%S"),
                    image_path=rec.image_path,
                    zone_type=zone_type,
                    unauthorized_person=rec.similarity_id
                )

                ALLOWED_PLACE_LAST_ALERT[rule_key] = now
                continue


# -----------------RESTRICTED ZONE RULE-------------
from webapp.mailer import send_restricted_zone_alert

RESTRICTED_ZONE_LAST_ALERT = {}

def execute_restricted_zone_rules():
    now = datetime.now()

    try:
        rule_obj = Rule.objects.get(rule_type="restricted_zone")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():
        zone_type = rule.get("zone_type","Zone")
        # ---------- TIME CHECK ----------
        if rule.get("time_mode") == "custom":
            now_time = now.time()

            start = datetime.strptime(rule["start_time"], "%H:%M").time()
            end = datetime.strptime(rule["end_time"], "%H:%M").time()

            if not (start <= now_time <= end):
                continue


        if not rule.get("active"):
            continue

        restricted_depts = rule.get("restricted_departments", [])   
        cameras = rule["place"]                               
        email = rule["head_email"]

        recent_start = now - timedelta(minutes=1)
        
        records = (
            RecognizedFace.objects
            .filter(
                camera_name__in=cameras,
                capture_date_time__gte=recent_start
            )
            .order_by("-capture_date_time")
        )

        for r in records:

            unique_key = f"{r.id}_{rule_key}"

            if unique_key in RESTRICTED_ZONE_LAST_ALERT:
                continue

            RESTRICTED_ZONE_LAST_ALERT[unique_key] = now

            emp = Employee.objects.filter(emp_id=r.emp_id).first()

            # ---------- CONFIRMED EMPLOYEE ----------
            if r.emp_id and emp and emp.dept in restricted_depts:

                send_restricted_zone_alert(
                    to_email=email,
                    emp_id=emp.emp_id,
                    emp_name=emp.emp_name,
                    emp_dept=emp.dept,
                    unauthorized_person=None,
                    place=r.camera_name,
                    time_str=r.capture_date_time.strftime("%H:%M:%S"),
                    image_path=r.image_path,
                    zone_type=zone_type
                )
                continue


            # ---------- UNAUTHORIZED PERSON ----------
            if not r.emp_id and r.similarity_id:

                send_restricted_zone_alert(
                    to_email=email,
                    emp_id=None,
                    emp_name=None,
                    emp_dept=None,
                    unauthorized_person=r.similarity_id,
                    place=r.camera_name,
                    time_str=r.capture_date_time.strftime("%H:%M"),
                    image_path=r.image_path,
                    zone_type=zone_type
                )
                continue

# -----------------IN/OUT TIME RULE-------------
from webapp.mailer import send_inout_time_alert

INOUT_SENT_TODAY = {}     
BREAK_LAST_ALERT = {}     

def execute_inout_time_rules():

    now = datetime.now()
    today = now.date()
    today_key = today.strftime("%Y-%m-%d")

    try:
        rule_obj = Rule.objects.get(rule_type="inout_time")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():

        if not rule.get("active", False):
            continue

        head_email = rule.get("head_email")
        if not head_email:
            continue

        # ================= ATTENDANCE =================

        attendance = rule["attendance"]

        try:
            in_before = datetime.strptime(attendance["in_before"], "%H:%M").time()
            out_after = datetime.strptime(attendance["out_after"], "%H:%M").time()
        except (KeyError, ValueError):
            continue  # skip rule if time format is invalid

        attendance_places = attendance.get("place", [])

        if not attendance_places:
            continue

        records = (
            RecognizedFace.objects
            .filter(
                capture_date_time__date=today,
                camera_name__in=attendance_places
            )
            .exclude(emp_id__in=["", "UNKNOWN", "NO_FACE"])
            .order_by("capture_date_time")
        )

        emp_map = {}
        for r in records:
            emp_map.setdefault(r.emp_id, []).append(r)

        for emp_id, recs in emp_map.items():

            emp = Employee.objects.filter(emp_id=emp_id).first()
            if not emp:
                continue

            if not recs:
                continue

            first = recs[0]
            last = recs[-1]

            # ---------- LATE ENTRY ----------
            late_key = f"{today_key}_{emp.emp_id}_late"

            if first.capture_date_time.time() > in_before and not INOUT_SENT_TODAY.get(late_key):

                send_inout_time_alert(
                    to_email=head_email,
                    employee=emp,
                    violation_type="Late Entry",
                    violation_time=first.capture_date_time.strftime("%H:%M"),
                    image_path=first.image_path,
                    place=first.camera_name
                )

                INOUT_SENT_TODAY[late_key] = True

            # ---------- EARLY EXIT ----------
            early_key = f"{today_key}_{emp.emp_id}_early"

            if now.time() > out_after:
                if last.capture_date_time.time() < out_after and not INOUT_SENT_TODAY.get(early_key):

                    send_inout_time_alert(
                        to_email=head_email,
                        employee=emp,
                        violation_type="Early Exit",
                        violation_time=last.capture_date_time.strftime("%H:%M"),
                        image_path=last.image_path,
                        place=last.camera_name
                    )

                    INOUT_SENT_TODAY[early_key] = True

        # ================= BREAK RULES =================

        for idx, br in enumerate(rule.get("breaks", [])):

            try:
                br_end = datetime.strptime(br["end"], "%H:%M").time()
            except (KeyError, ValueError):
                continue

            places = br.get("place", [])

            if not places:
                continue

            recent_start = now - timedelta(minutes=5)
            break_key = f"{rule_key}_break_{idx}"

            last_sent = BREAK_LAST_ALERT.get(break_key)
            if last_sent and (now - last_sent).total_seconds() < 300:
                continue

            break_records = (
                RecognizedFace.objects
                .filter(
                    camera_name__in=places,
                    capture_date_time__gte=recent_start
                )
                .exclude(emp_id__in=["", "UNKNOWN", "NO_FACE"])
                .order_by("-capture_date_time")
            )

            for rec in break_records:

                emp = Employee.objects.filter(emp_id=rec.emp_id).first()
                if not emp:
                    continue

                # employee still in break area after allowed time
                if rec.capture_date_time.time() > br_end:

                    send_inout_time_alert(
                        to_email=head_email,
                        employee=emp,
                        violation_type=f"Break Overstay ({br.get('name','Break')})",
                        violation_time=rec.capture_date_time.strftime("%H:%M"),
                        image_path=rec.image_path,
                        place=rec.camera_name
                    )

                    BREAK_LAST_ALERT[break_key] = now
                    break  

# -----------------UNKNOW PERSON RULE-------------
from webapp.mailer import send_unknown_alert

UNKNOWN_SENT = set()   

def execute_unknown_alert_rule():
    now = datetime.now()

    try:
        rule_obj = Rule.objects.get(rule_type="unknown_alert")
    except Rule.DoesNotExist:
        return

    rule = rule_obj.rules_json.get("rule_1")
    if not rule or not rule.get("active"):
        return

    head_email = rule.get("head_email")
    if not head_email:
        return

    # ⏱ last 10 minutes only
    recent_start = now - timedelta(minutes=10)

    unknown_faces = (
        RecognizedFace.objects
        .filter(
            capture_date_time__gte=recent_start
        )
        .filter(
            similarity_id="UNKNOWN"
        )
    )

    for rec in unknown_faces:

        # ❌ already mailed
        if rec.id in UNKNOWN_SENT:
            continue

        send_unknown_alert(
            to_email=head_email,
            camera_name=rec.camera_name,
            time_str=rec.capture_date_time.strftime("%H:%M:%S"),
            image_path=rec.image_path
        )

        UNKNOWN_SENT.add(rec.id)


# -----------------PHONE USAGE RULE--------------
from webapp.mailer import send_phone_usage_alert

def execute_phone_usage_rules():
    try:
        rule = Rule.objects.get(rule_type="phone_usage")
    except Rule.DoesNotExist:
        return

    rules = rule.rules_json or {}

    for _, r in rules.items():

        if not r.get("active"):
            continue

        cameras = r["place"]
        head_email = r["head_email"]

        # ✅ ONLY UNSENT PHONE EVENTS
        records = (
            RecognizedFace.objects
            .filter(
                camera_name__in=cameras,
                phone_detected=True,
                phone_mail_sent=False   # 🔥 KEY FIX
            )
            .order_by("capture_date_time")[:5]
        )

        for rec in records:
            if not rec.emp_id:
                continue

            emp = Employee.objects.filter(emp_id=rec.emp_id).first()
            if not emp:
                continue

            send_phone_usage_alert(
                to_email=head_email,
                emp=emp,
                place=rec.camera_name,
                time_str=rec.capture_date_time.strftime("%H:%M"),
                image_path=rec.image_path
            )

            # ✅ MARK AS SENT (THIS PREVENTS REPEAT)
            rec.phone_mail_sent = True
            rec.save(update_fields=["phone_mail_sent"])


#-------------SAFETY RULE--------------------------------
from webapp.mailer import send_helmet_alert

HELMET_LAST_ALERT = {}

def execute_helmet_rules():
    now = datetime.now()
    recent_start = now - timedelta(minutes=1)

    try:
        rule_obj = Rule.objects.get(rule_type="helmet")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():

        if not rule.get("active", False):
            continue

        cams = rule.get("place", [])
        email = rule.get("head_email")

        if not cams or not email:
            continue

        # 🔥 all employee violations
        violations = (
            RecognizedFace.objects
            .filter(
                camera_name__in=cams,
                capture_date_time__gte=recent_start,
                helmet_detected=False,
                emp_id__isnull=False
            )
            .exclude(emp_id="")
            .order_by("-capture_date_time")
        )

        for v in violations:

            throttle_key = f"{rule_key}_{v.emp_id}"
            last = HELMET_LAST_ALERT.get(throttle_key)

            # ⏱ 10 min throttle per employee
            if last and (now - last).total_seconds() < 300:
                continue

            employee = Employee.objects.filter(emp_id=v.emp_id).first()
            if not employee:
                continue

            # 📧 SEND MAIL (PER EMPLOYEE)
            send_helmet_alert(
                to_email=email,
                place=v.camera_name,
                time_str=v.capture_date_time.strftime("%H:%M"),
                emp=employee,
                image_path=v.image_path
            )

            HELMET_LAST_ALERT[throttle_key] = now
            
            
#-----------------No Employee RULE-------------    
from webapp.mailer import send_no_employee_alert   
COUNT_BUFFER = {}  
LAST_ALERT = {}   

def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)):
            x_intersect = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
            if x_intersect < x:
                inside = not inside
    return inside

def execute_no_employee_rules():
    if not views.streams:
        return
    now = datetime.now()
    try:
        rule_obj = Rule.objects.get(rule_type="no_employee")
    except Rule.DoesNotExist:
        return
    rules = rule_obj.rules_json or {}

    for key, rule in rules.items():

        if not rule.get("active"):
            continue
        cameras = [c.strip() for c in rule.get("cameras", [])]
        min_count = int(rule.get("min_count") or 0)
        duration = int(rule.get("duration_minutes") or 1)
        break_start = rule.get("break_start")
        break_end = rule.get("break_end")
        email = rule.get("head_email")
        boundaries_per_camera = rule.get("boundaries", {})

        # Break skip
        if break_start and break_end:
            try:
                start = datetime.strptime(break_start, "%H:%M").time()
                end = datetime.strptime(break_end, "%H:%M").time()
                if start <= now.time() <= end:
                    continue
            except:
                pass

        for cam in cameras:
            #print("📷 Cameras:", cameras)
            stream = views.streams.get(cam)
            if not stream:
                #print(f"❌ No stream found for {cam}")
                continue
            #print(f"✅ Stream found for {cam}")
            
            frame = stream.get_frame()
            if frame is None:
                #print("❌ Frame is None")
                continue
            #print("✅ Frame Received")

            # Use rule + camera as key (no boundary names)
            buffer_key = f"{key}_{cam}"

            # Get selected boundary names for this camera
            selected_boundary_names = boundaries_per_camera.get(cam, [])

            # Load boundary polygons from database
            boundary_polygons = []
            if selected_boundary_names:
                try:
                    boundaries = CameraBoundary.objects.filter(
                        camera_name=cam,
                        boundary_name__in=selected_boundary_names
                    )
                    boundary_polygons = [b.points for b in boundaries]
                except Exception as e:
                    print(f"Error loading boundaries for {cam}: {e}")

            # Get recent people detections
            recent = RecognizedFace.objects.filter(
                camera_name=cam,
                capture_date_time__gte=now - timedelta(minutes=2)
            )
            #print(f"👤 Recent detections count: {recent.count()}")

            # Count people inside ANY of the selected boundaries
            count = 0
            if boundary_polygons:
                for rec in recent:
                    if rec.bbox and len(rec.bbox) == 4:
                        center_x = (rec.bbox[0] + rec.bbox[2]) // 2
                        center_y = (rec.bbox[1] + rec.bbox[3]) // 2
                        if any(point_in_polygon((center_x, center_y), poly) for poly in boundary_polygons):
                            count += 1
            else:
                count = recent.count()

            if count <= min_count:
                if buffer_key not in COUNT_BUFFER:
                    COUNT_BUFFER[buffer_key] = now
                    #print(f"⏱️ Timer started for {cam} at {now.strftime('%H:%M:%S')}")
                
                elapsed = (now - COUNT_BUFFER[buffer_key]).total_seconds()
                
                if elapsed >= duration * 60:
                    last = LAST_ALERT.get(buffer_key)
                    if not last or (now - last).total_seconds() >= duration * 60:
                        start_time = COUNT_BUFFER[buffer_key]
                        image_path = save_full_frame(cam, frame)
                        time_range = f"{start_time.strftime('%H:%M')} - {now.strftime('%H:%M')}"
                        
                        #print(f"🚨 ALERT: {cam} - No people for {duration} minute(s)")
                        send_no_employee_alert(email, cam, count, start_time, now, image_path, time_range)
                        
                        LAST_ALERT[buffer_key] = now
                        COUNT_BUFFER[buffer_key] = now
            else:
                # People detected - reset everything
                if buffer_key in COUNT_BUFFER:
                    #print(f"✅ People detected in {cam} - Resetting timer")
                    COUNT_BUFFER.pop(buffer_key, None)
                    LAST_ALERT.pop(buffer_key, None)
                

#-----------------Group Detection RULE-------------  
from webapp.mailer import send_group_alert  
from webapp.group_detection import detect_groups
import cv2
from webapp.group_detection import detect_groups, draw_annotations

try:
    from webapp.group_detection import THRESHOLD_PERCENT, USE_FRAME_INTERVAL, FRAME_INTERVAL_SECONDS
except ImportError:
    THRESHOLD_PERCENT = 80
    USE_FRAME_INTERVAL = True
    FRAME_INTERVAL_SECONDS = 2

WINDOW_STATE = {}          
_LAST_PROCESS_TIME = {}


def is_break_time(break_start, break_end, current_time):
    if not break_start or not break_end:
        return False
    try:
        bs = datetime.strptime(break_start, "%H:%M").time()
        be = datetime.strptime(break_end, "%H:%M").time()
        return bs <= current_time.time() <= be
    except:
        return False


def get_window_key(rule_key, cam_name):
    return f"{rule_key}_{cam_name}"


def init_window(key, window_duration_minutes, now):
    """Initialize a new window with per-section tracking"""
    window_start = now
    window_end = now + timedelta(minutes=window_duration_minutes)
    
    WINDOW_STATE[key] = {
        'window_start': window_start,
        'window_end': window_end,
        'sections': {},
        'last_update': now,
        'alert_sent': False,
        'triggered_section': None,
        'window_completed': False,
        'last_groups': [],          # last groups (from current detection)
        'last_persons': [],         # last persons (alert persons)
        'last_frame': None,         # raw frame from last detection
        'max_group_frame': None,    # frame where max group occurred
        'max_group_data': None,     # (groups, alert_persons) at max group
    }
    
    # Initialize 4 sections
    for i in range(4):
        WINDOW_STATE[key]['sections'][i] = {'time': 0.0, 'max_size': 0}
    
    # print(f"\n{'='*60}")
    # print(f"📊 NEW WINDOW STARTED")
    # print(f"   Start: {window_start.strftime('%Y-%m-%d %H:%M:%S')}")
    # print(f"   End:   {window_end.strftime('%Y-%m-%d %H:%M:%S')}")
    # print(f"   Duration: {window_duration_minutes} minutes")
    # print(f"   Threshold: {THRESHOLD_PERCENT}%")
    # print(f"{'='*60}\n")
    
    return window_start, window_end


def update_window_state(key, now, groups, alert_persons, frame, max_allowed):
    state = WINDOW_STATE.get(key)
    if not state or state.get('window_completed'):
        return
    
    state['last_groups'] = groups
    state['last_persons'] = alert_persons
    state['last_frame'] = frame
    
    # Track which sections have exceeding groups
    sections_active = set()
    for group in groups:
        section = group.get('section', 0)
        group_size = group['size']
        if group_size > max_allowed:
            sections_active.add(section)
            if group_size > state['sections'][section]['max_size']:
                state['sections'][section]['max_size'] = group_size
                # Store this frame and data as the best for this window
                state['max_group_frame'] = frame
                state['max_group_data'] = (groups, alert_persons)
    
    # Time elapsed since last update
    time_diff = (now - state['last_update']).total_seconds()
    if time_diff <= 0 or time_diff > 10:
        time_diff = FRAME_INTERVAL_SECONDS
    
    # Add time to active sections
    for section_id in sections_active:
        state['sections'][section_id]['time'] += time_diff
    
    state['last_update'] = now


def check_and_trigger_alert(key, now, window_duration_minutes, threshold_percent,
                            cam_name, email, max_allowed, frame, rule_key):
    state = WINDOW_STATE.get(key)
    if not state or state.get('window_completed'):
        return False
    
    if now >= state['window_end']:
        state['window_completed'] = True
        
        window_duration_seconds = window_duration_minutes * 60
        
        # print(f"\n{'='*60}")
        # print(f"📊 WINDOW COMPLETED")
        # print(f"   Window: {state['window_start'].strftime('%H:%M:%S')} - {state['window_end'].strftime('%H:%M:%S')}")
        # print(f"   Duration: {window_duration_minutes} minutes")
        # print(f"   Threshold: {threshold_percent}%")
        # print(f"\n   📍 Section breakdown:")
        
        threshold_sections = []
        for section_id, data in state['sections'].items():
            section_time = data['time']
            section_pct = (section_time / window_duration_seconds) * 100 if window_duration_seconds > 0 else 0
            # print(f"      Section {section_id+1}: {section_time:.1f}s ({section_pct:.1f}%) | Max group: {data['max_size']}")
            
            if section_pct >= threshold_percent:
                threshold_sections.append({
                    'id': section_id,
                    'percentage': section_pct,
                    'time': section_time,
                    'max_size': data['max_size']
                })
        
        #print(f"{'='*60}\n")
    
        if threshold_sections and not state.get('alert_sent'):
            threshold_sections.sort(key=lambda x: x['percentage'], reverse=True)
            best_section = threshold_sections[0]
            
            # print(f"🚨🚨🚨 ALERT TRIGGERED for Section {best_section['id']+1}!")
            # print(f"   Section {best_section['id']+1} exceeded {best_section['percentage']:.1f}% (threshold {threshold_percent}%)")
            # print(f"   Max group size: {best_section['max_size']} people")
            # print(f"   Total time: {best_section['time']:.1f}s")
            
            # ========== USE STORED DATA ==========
            stored_groups, stored_persons = state.get('max_group_data', (None, None))
            stored_frame = state.get('max_group_frame')
            
            if stored_persons is None or len(stored_persons) == 0:
                stored_groups = state.get('last_groups', [])
                stored_persons = state.get('last_persons', [])
                stored_frame = state.get('last_frame', frame)
                # print(f"   ⚠️ No max_group_data, using last stored (groups: {len(stored_groups)}, persons: {len(stored_persons)})")
            
            filtered_groups = [g for g in stored_groups if g.get('section', 0) == best_section['id']]
            filtered_persons = [p for p in stored_persons if p.get('section', 0) == best_section['id']]
            
            # print(f"   📸 Creating annotated image with {len(filtered_persons)} people and {len(filtered_groups)} groups")
            
            annotated_frame = draw_annotations(stored_frame, filtered_persons, filtered_groups, max_allowed + 1)
            
            # Add overlay text
            cv2.putText(annotated_frame, f"ALERT: Section {best_section['id']+1} - {best_section['percentage']:.1f}%", 
                       (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(annotated_frame, f"Time: {state['window_start'].strftime('%H:%M')} - {state['window_end'].strftime('%H:%M')}", 
                       (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            
            # Save image
            img_path = save_full_frame(cam_name, annotated_frame)
            
            # Prepare email
            person_lines = [f"  P{p['id']}: {p['distance']:.1f}m" for p in filtered_persons]
            group_lines = [f"  Group of {g['size']} people" for g in filtered_groups]
            
            extra_body = f"""
=== OVERCROWDING ALERT ===

Camera: {cam_name}
Alerting Section: Section {best_section['id']+1}
Section percentage: {best_section['percentage']:.1f}% (threshold {threshold_percent}%)
Time Window: {state['window_start'].strftime('%Y-%m-%d %H:%M')} - {state['window_end'].strftime('%H:%M')}
Total group time in section: {best_section['time']:.1f}s
Max group size: {best_section['max_size']} people

--- People in alert section ---
{chr(10).join(person_lines)}

--- Groups in alert section ---
{chr(10).join(group_lines)}
"""
            send_group_alert(
                to_email=email,
                place=cam_name,
                count=best_section['max_size'],
                start_time=state['window_start'],
                end_time=state['window_end'],
                image_path=img_path,
                extra_body=extra_body
            )
            
            state['alert_sent'] = True
            state['triggered_section'] = best_section['id']
        
        init_window(key, window_duration_minutes, now)
        return True
    
    return False


def execute_group_rules():
    if not views.streams:
        return

    now = datetime.now()

    try:
        rule_obj = Rule.objects.get(rule_type="group")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():
        if not rule.get("active"):
            continue

        cameras = rule.get("cameras", {})
        max_allowed = int(rule.get("max_count") or 1)
        duration_minutes = float(rule.get("duration_minutes") or 10)
        email = rule.get("head_email")
        group_distance = float(rule.get("group_distance", 1.0))
        break_start = rule.get("break_start")
        break_end = rule.get("break_end")
        threshold_percent = THRESHOLD_PERCENT

        # Skip break time
        if is_break_time(break_start, break_end, now):
            for cam_name in cameras.keys():
                key = get_window_key(rule_key, cam_name)
                WINDOW_STATE.pop(key, None)
            continue

        for cam_name, _ in cameras.items():
            stream = views.streams.get(cam_name)
            if not stream:
                continue

            # Frame interval contro
            process_key = f"{rule_key}_{cam_name}"
            if USE_FRAME_INTERVAL:
                last_time = _LAST_PROCESS_TIME.get(process_key)
                if last_time and (now - last_time).total_seconds() < FRAME_INTERVAL_SECONDS:
                    continue
                _LAST_PROCESS_TIME[process_key] = now

            frame = stream.get_frame()
            if frame is None:
                continue

            groups, _, alert_persons = detect_groups(
                frame,
                eps=group_distance,
                min_samples=2,
                alert_min_size=max_allowed + 1,
                camera_name=cam_name
            )

            key = get_window_key(rule_key, cam_name)
            
            if key not in WINDOW_STATE:
                init_window(key, duration_minutes, now)
            
            update_window_state(key, now, groups, alert_persons, frame, max_allowed)
            
            check_and_trigger_alert(
                key, now, duration_minutes, threshold_percent,
                cam_name, email, max_allowed, frame, rule_key
            )
            
            state = WINDOW_STATE.get(key)
            if state and not state.get('window_completed'):
                last_status_print = getattr(execute_group_rules, f'_last_status_{key}', None)
                if last_status_print is None or (now - last_status_print).total_seconds() >= 30:
                    elapsed = (now - state['window_start']).total_seconds()
                    remaining = (state['window_end'] - now).total_seconds()
                    window_duration_seconds = duration_minutes * 60
                    
                    # print(f"\n📈 [PROGRESS] {cam_name}")
                    # print(f"   Window: {state['window_start'].strftime('%H:%M:%S')} - {state['window_end'].strftime('%H:%M:%S')}")
                    # print(f"   Time remaining: {remaining:.0f}s")
                    
                    for section_id, data in state['sections'].items():
                        if data['time'] > 0:
                            section_pct = (data['time'] / window_duration_seconds) * 100 if window_duration_seconds > 0 else 0
                            #print(f"   Section {section_id+1}: {data['time']:.1f}s ({section_pct:.1f}%) | Max: {data['max_size']}")
                    
                    setattr(execute_group_rules, f'_last_status_{key}', now)
                    
# ================= WORK DETECTION RULE EXECUTOR =================

# Global state for work rule tracking - EFFICIENT VERSION
WORK_SESSION_DATA = {}  # key: f"{rule_key}_{cam}_{schedule_start}_{schedule_end}"

def point_in_polygon(point, polygon):
    """Check if point is inside polygon"""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)):
            x_intersect = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
            if x_intersect < x:
                inside = not inside
    return inside


def get_employee_count_from_frame(camera_name, frame, boundary_polygons):
    """
    Detect humans in current frame using YOLO
    Returns: (has_human, count)
    """
    from ultralytics import YOLO
    import threading
    
    # Thread-local YOLO model
    _thread_local = threading.local()
    if not hasattr(_thread_local, "yolo_model"):
        _thread_local.yolo_model = YOLO("yolov8n.pt")
    
    model = _thread_local.yolo_model
    
    # Detect persons (class 0)
    results = model(frame, classes=[0], conf=0.4, verbose=False)
    
    if len(results) == 0 or results[0].boxes is None:
        return False, 0
    
    boxes = results[0].boxes.xyxy.cpu().numpy()
    
    if boundary_polygons:
        # Filter by boundaries
        count = 0
        for box in boxes:
            x1, y1, x2, y2 = map(int, box[:4])
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            if any(point_in_polygon((center_x, center_y), poly) for poly in boundary_polygons):
                count += 1
        return count > 0, count
    else:
        return len(boxes) > 0, len(boxes)


def save_alert_frame(camera_name, frame):
    """Save frame for alert evidence"""
    from webapp.face_core import save_full_frame
    import os
    from datetime import datetime
    
    try:
        # Save full frame using existing function
        image_path = save_full_frame(camera_name, frame)
        return image_path
    except Exception as e:
        print(f"Error saving alert frame: {e}")
        
        # Fallback: save directly
        try:
            from django.conf import settings
            from pathlib import Path
            
            # Create directory
            save_dir = Path(settings.MEDIA_ROOT) / "work_alerts"
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # Save image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{camera_name}_{timestamp}.jpg"
            filepath = save_dir / filename
            
            import cv2
            cv2.imwrite(str(filepath), frame)
            
            # Return relative path
            return f"work_alerts/{filename}"
        except Exception as e2:
            print(f"Fallback save also failed: {e2}")
            return None


def execute_work_rules():
    from webapp.mailer import send_work_alert
    
    if not views.streams:
        return
    
    now = datetime.now()
    current_time = now.time()
    
    try:
        rule_obj = Rule.objects.get(rule_type="work")
    except Rule.DoesNotExist:
        return
    
    rules = rule_obj.rules_json or {}
    
    for rule_key, rule in rules.items():
        if not rule.get('active', True):
            continue
        
        cameras = rule.get('cameras', [])
        threshold_minutes = rule.get('min_count', 5)
        email = rule.get('email')
        work_schedules = rule.get('work_schedules', [])
        boundaries_per_camera = rule.get('boundaries', {})
        
        for schedule in work_schedules:
            try:
                work_start = datetime.strptime(schedule['start'], "%H:%M").time()
                work_end = datetime.strptime(schedule['end'], "%H:%M").time()
                
                # ========== FIRST: Check for sessions that need final alert ==========
                for session_key in list(WORK_SESSION_DATA.keys()):
                    session = WORK_SESSION_DATA[session_key]
                    if session.get('rule_key') != rule_key:
                        continue
                    
                    session_end_time = session.get('work_end_time')
                    if session_end_time:
                        end_datetime = datetime.combine(now.date(), session_end_time)
                        
                        if current_time > session_end_time or (now - end_datetime).total_seconds() > 0:
                            if not session.get('final_alert_sent'):
                                total_human_minutes = session.get('total_human_seconds', 0) / 60
                                cam = session.get('camera')
                                
                                # print(f"\n[WORK][{cam}] ========== WORK PERIOD ENDED ==========")
                                # print(f"[WORK][{cam}] End time detected: {now.strftime('%H:%M:%S')}")
                                # print(f"[WORK][{cam}] Total human presence: {total_human_minutes:.1f} minutes")
                                # print(f"[WORK][{cam}] Required threshold: {threshold_minutes} minutes")
                                
                                if total_human_minutes < threshold_minutes:
                                    # print(f"[WORK][{cam}] 🚨 WORK ATTENDANCE ALERT: Only {total_human_minutes:.1f} minutes worked")
                                    
                                    # Get last frame for evidence
                                    stream = views.streams.get(cam)
                                    frame = None
                                    image_path = None
                                    if stream:
                                        frame = stream.get_frame()
                                        if frame is not None:
                                            image_path = save_alert_frame(cam, frame)
                                    
                                    send_work_alert(
                                        session.get('email'), cam, int(total_human_minutes), threshold_minutes,
                                        session.get('session_start'), now,
                                        image_path,
                                        f"Only {total_human_minutes:.1f} minutes worked (need {threshold_minutes})"
                                    )
                                else:
                                    pass
                                    # print(f"[WORK][{cam}] ✅ OK: Employee worked {total_human_minutes:.1f} minutes")
                                
                                session['final_alert_sent'] = True
                                
                                # Clean up session after alert
                                del WORK_SESSION_DATA[session_key]
                                print(f"[WORK][{cam}] Session cleaned up\n")
                
                # ========== SECOND: Check if within work period ==========
                if not (work_start <= current_time <= work_end):
                    continue
                
                start_datetime = datetime.combine(now.date(), work_start)
                end_datetime = datetime.combine(now.date(), work_end)
                
                for cam in cameras:
                    session_key = f"{rule_key}_{cam}_{work_start.strftime('%H%M')}_{work_end.strftime('%H%M')}"
                    
                    # Get current frame
                    stream = views.streams.get(cam)
                    if not stream:
                        continue
                    
                    frame = stream.get_frame()
                    if frame is None:
                        continue
                    
                    # Get boundary polygons
                    selected_boundary_names = boundaries_per_camera.get(cam, [])
                    boundary_polygons = []
                    if selected_boundary_names:
                        try:
                            boundaries = CameraBoundary.objects.filter(
                                camera_name=cam,
                                boundary_name__in=selected_boundary_names
                            )
                            boundary_polygons = [b.points for b in boundaries if b.points]
                        except Exception as e:
                            print(f"Error loading boundaries for {cam}: {e}")
                    
                    # Detect humans in current frame
                    has_human, human_count = get_employee_count_from_frame(cam, frame, boundary_polygons)
                    
                    # Status icon for terminal
                    status_icon = "👤" if has_human else "❌"
                    # print(f"[WORK][{cam}] {status_icon} Human: {human_count} at {now.strftime('%H:%M:%S')}")
                    
                    # Initialize or update session
                    if session_key not in WORK_SESSION_DATA:
                        WORK_SESSION_DATA[session_key] = {
                            'session_start': now,
                            'total_human_seconds': 0,
                            'last_update_time': now,
                            'was_human_last_check': False,
                            'no_employee_alert_sent': False,
                            'final_alert_sent': False,
                            'threshold_minutes': threshold_minutes,
                            'work_end_time': work_end,
                            'camera': cam,
                            'email': email,
                            'rule_key': rule_key,
                            'last_alert_image': None
                        }
                        # print(f"\n[WORK][{cam}] ========== SESSION START ==========")
                        # print(f"[WORK][{cam}] Work: {work_start} - {work_end}, Threshold: {threshold_minutes} min")
                        # print(f"[WORK][{cam}] Start time: {now.strftime('%H:%M:%S')}")
                    
                    session = WORK_SESSION_DATA[session_key]
                    
                    # Calculate time since last update (should be ~5 seconds)
                    time_diff = (now - session['last_update_time']).total_seconds()
                    
                    # Update total human seconds if human was present during this interval
                    if session['was_human_last_check']:
                        session['total_human_seconds'] += min(time_diff, 10)
                    
                    # Update for next check
                    session['last_update_time'] = now
                    session['was_human_last_check'] = has_human
                    
                    # Calculate elapsed minutes since session start
                    elapsed_seconds = (now - session['session_start']).total_seconds()
                    elapsed_minutes = elapsed_seconds / 60
                    
                    # ========== CHECKPOINT: Threshold check (No Employee Alert) ==========
                    if not session['no_employee_alert_sent'] and elapsed_minutes >= threshold_minutes:
                        if session['total_human_seconds'] == 0:
                            # print(f"\n[WORK][{cam}] 🚨 NO EMPLOYEE ALERT at {now.strftime('%H:%M:%S')}")
                            # print(f"[WORK][{cam}] No human detected in first {threshold_minutes} minutes")
                            
                            # Save frame for evidence
                            image_path = save_alert_frame(cam, frame)
                            session['last_alert_image'] = image_path
                            
                            send_work_alert(
                                email, cam, 0, threshold_minutes,
                                session['session_start'],
                                now,
                                image_path,
                                f"No employee detected in first {threshold_minutes} minutes"
                            )
                        else:
                            human_minutes = session['total_human_seconds'] / 60
                            print(f"\n[WORK][{cam}] ✓ Human detected: {human_minutes:.1f} minutes in first {threshold_minutes} min")
                        
                        session['no_employee_alert_sent'] = True
                    
            except Exception as e:
                print(f"Error processing schedule: {e}")
                import traceback
                traceback.print_exc()
                continue
    
    for session_key in list(WORK_SESSION_DATA.keys()):
        session = WORK_SESSION_DATA[session_key]
        work_end = session.get('work_end_time')
        if work_end:
            end_datetime = datetime.combine(now.date(), work_end)
            if now > end_datetime + timedelta(hours=1):
                print(f"[WORK] Cleaning stale session: {session_key}")
                del WORK_SESSION_DATA[session_key]