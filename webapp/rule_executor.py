from datetime import datetime, time
from webapp.models import Rule, Employee, RecognizedFace
from datetime import timedelta
import math
from collections import defaultdict


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


# -----------------GROUP GATHERING RULE--------------
from webapp.mailer import send_group_gathering_alert

def bbox_center(bbox):
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)

def euclidean_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def count_close_people(centers, threshold):
    close_people = set()

    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            if euclidean_distance(centers[i], centers[j]) < threshold:
                close_people.add(i)
                close_people.add(j)

    return len(close_people)


GROUP_LAST_ALERT = {}

def execute_group_gathering_rules():
    now = datetime.now()
    recent_start = now - timedelta(minutes=2)

    DISTANCE_THRESHOLD = 80  # pixels (tune per camera)

    try:
        rule_obj = Rule.objects.get(rule_type="group_gathering")
    except Rule.DoesNotExist:
        return

    rules = rule_obj.rules_json or {}

    for rule_key, rule in rules.items():

        if not rule.get("active", False):
            continue

        # ⏱ throttle (10 min per rule)
        last_sent = GROUP_LAST_ALERT.get(rule_key)
        if last_sent and (now - last_sent).total_seconds() < 300:
            continue

        camera_names = rule["place"]
        max_count = int(rule["max_count"])
        head_email = rule["head_email"]

        # ---------- FETCH RECENT RECORDS (ALL PEOPLE) ----------
        records = (
            RecognizedFace.objects
            .filter(
                camera_name__in=camera_names,
                capture_date_time__gte=recent_start
            )
            .exclude(bbox__isnull=True)
            .order_by("-capture_date_time")
        )

        if not records.exists():
            continue

        # ---------- GROUP BY CAMERA ----------
        cam_map = defaultdict(list)
        for r in records:
            cam_map[r.camera_name].append(r)

        # ---------- PROCESS EACH CAMERA ----------
        for cam, recs in cam_map.items():

            centers = []
            known_emp_ids = set()

            for r in recs:
                try:
                    centers.append(bbox_center(r.bbox))

                    # collect ONLY known employees
                    if r.emp_id and r.emp_id not in ["UNKNOWN", "NO_FACE"]:
                        known_emp_ids.add(r.emp_id)
                except:
                    continue

            if len(centers) < 1:
                continue

            close_count = count_close_people(centers, DISTANCE_THRESHOLD)

            # ---------- RULE VIOLATION ----------
            if close_count > max_count:

                employees = (
                    Employee.objects
                    .filter(emp_id__in=known_emp_ids)
                    .values_list("emp_id", "emp_name")
                )

                emp_lines = [
                    f"{e[0]} - {e[1]}" for e in employees
                ]

                known_count = len(known_emp_ids)
                unknown_count = max(close_count - known_count, 0)

                send_group_gathering_alert(
                    to_email=head_email,
                    place=cam,
                    detected_count=close_count,
                    allowed_count=max_count,
                    employees="\n".join(emp_lines),
                    known_count=known_count,
                    unknown_count=unknown_count,
                    time_str=now.strftime("%H:%M")
                )

                GROUP_LAST_ALERT[rule_key] = now
                break  # ✅ one mail per cycle


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