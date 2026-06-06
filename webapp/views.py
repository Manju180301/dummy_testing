import platform
from django.shortcuts import render
import  numpy as np
from django.http import StreamingHttpResponse, Http404
from django.core.files.storage import default_storage
from pathlib import Path
from datetime import datetime
from django.shortcuts import  get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
import cv2, os
from django.conf import settings
from django.db.models import Q
import time
from django.db.models.functions import Trim
from datetime import datetime, date ,timedelta
from webapp.apps import WebappConfig
from django.db.models import Count
from django.db.models.functions import TruncHour, TruncDay, TruncMonth
import json
from webapp import views
from collections import OrderedDict
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .models import Employee, FaceRecording ,RecognizedFace,Rule
from django.core.paginator import Paginator
from .models import EmailSend
import csv

import threading
dvr_ready_event = threading.Event()


def index(request):
    COMPANY_ID = "1060"

    # ================= BASIC COUNTS =================
    employees = Employee.objects.filter(company_id=COMPANY_ID)

    total_employees = employees.count()
    total_cameras = len(views.streams)

    # ================= TODAY PRESENT =================
    today = date.today()
    start_dt = datetime.combine(today, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())

    today_present = (
        RecognizedFace.objects
        .filter(capture_date_time__range=(start_dt, end_dt))
        .exclude(emp_id__isnull=True)
        .exclude(emp_id="")
        .values("emp_id")
        .distinct()
        .count()
    )

    attendance_percentage = (
        round((today_present / total_employees) * 100, 2)
        if total_employees else 0
    )

    # =========================================================
    # WEEK DATA
    # =========================================================
    start_week = today - timedelta(days=today.weekday())

    week_labels = []
    week_values = []

    for i in range(7):
        day = start_week + timedelta(days=i)

        count = (
            RecognizedFace.objects
            .filter(capture_date_time__date=day)
            .exclude(emp_id__isnull=True)
            .exclude(emp_id="")
            .values("emp_id")
            .distinct()
            .count()
        )

        percent = round((count / total_employees) * 100, 1) if total_employees else 0

        week_labels.append(day.strftime("%A"))
        week_values.append(percent)

    # =========================================================
    # MONTH DATA
    # =========================================================
    import calendar

    month_labels = []
    month_values = []

    current_year = today.year

    for m in range(1, 13):

        days_in_month = calendar.monthrange(current_year, m)[1]

        total_present = (
            RecognizedFace.objects
            .filter(
                capture_date_time__year=current_year,
                capture_date_time__month=m
            )
            .exclude(emp_id__isnull=True)
            .exclude(emp_id="")
            .values("capture_date_time__date", "emp_id")
            .distinct()
            .count()
        )

        max_possible = total_employees * days_in_month

        if max_possible > 0:
            percent = round((total_present / max_possible) * 100, 1)
        else:
            percent = 0

        month_labels.append(datetime(2000, m, 1).strftime("%b"))
        month_values.append(percent)

    # =========================================================
    # YEAR DATA (last 7 years)
    # =========================================================
    year_labels = []
    year_values = []

    for y in range(current_year - 6, current_year + 1):

        total_present = (
            RecognizedFace.objects
            .filter(capture_date_time__year=y)
            .exclude(emp_id__isnull=True)
            .exclude(emp_id="")
            .values("capture_date_time__date", "emp_id")
            .distinct()
            .count()
        )

        days_in_year = 366 if calendar.isleap(y) else 365
        max_possible = total_employees * days_in_year

        if max_possible > 0:
            percent = round((total_present / max_possible) * 100, 1)
        else:
            percent = 0

        year_labels.append(str(y))
        year_values.append(percent)
        
    # ================= CAMERA DROPDOWN =================
    camera_names = list(views.streams.keys())

    month_list = [
    {"num":1,"name":"Jan"},
    {"num":2,"name":"Feb"},
    {"num":3,"name":"Mar"},
    {"num":4,"name":"Apr"},
    {"num":5,"name":"May"},
    {"num":6,"name":"Jun"},
    {"num":7,"name":"Jul"},
    {"num":8,"name":"Aug"},
    {"num":9,"name":"Sep"},
    {"num":10,"name":"Oct"},
    {"num":11,"name":"Nov"},
    {"num":12,"name":"Dec"},
    ]


    # ================= CONTEXT =================
    context = {
        "employees": employees,

        "total_employees": total_employees,
        "company_id": COMPANY_ID,
        "total_cameras": total_cameras,

        "present_count": today_present,
        "attendance_percentage": attendance_percentage,

        "week_labels": json.dumps(week_labels),
        "week_values": json.dumps(week_values),

        "month_labels": json.dumps(month_labels),
        "month_values": json.dumps(month_values),

        "year_labels": json.dumps(year_labels),
        "year_values": json.dumps(year_values),
        
        "camera_names":camera_names,
        "month_list":month_list,

    }

    return render(request, "webapp/index.html", context)

def camera_chart_api(request):

    camera = request.GET.get("camera")
    month = request.GET.get("month")

    if not camera or not month:
        return JsonResponse({"emp":0,"unknown":0,"noface":0})

    records = RecognizedFace.objects.filter(
        camera_name=camera,
        capture_date_time__month=month
    )

    total = records.count()

    if total == 0:
        return JsonResponse({"emp":0,"unknown":0,"noface":0})

    emp = records.exclude(emp_id__isnull=True).exclude(emp_id="").count()
    unknown = records.filter(similarity_id="UNKNOWN").count()
    noface = records.filter(similarity_id="NO_FACE").count()

    return JsonResponse({
        "emp": emp,
        "unknown": unknown,
        "noface": noface,
    })



#--------------Face Register--------------------
def face_register(request):
    if request.method != "POST":
        return render(request, 'webapp/face_register.html')

    company_id  = request.POST.get('company_id', '').strip()
    emp_name    = request.POST.get('emp_name', '').strip()
    emp_id      = request.POST.get('emp_id', '').strip()
    emp_type    = request.POST.get('emp_type', '').strip()
    dept        = request.POST.get('dept', '').strip()
    designation = request.POST.get('designation', '').strip()
    profile_pic = request.FILES.get("profile_pic")
    agree_terms = request.POST.get('agree_terms') == 'on'

    if not (company_id and emp_name and emp_id):
        return JsonResponse({"error": "Missing required fields"}, status=400)

    if Employee.objects.filter(company_id=company_id, emp_id=emp_id).exists():
        return JsonResponse({"error": "Employee already exists"}, status=409)

    employee = Employee.objects.create(
        company_id=company_id,
        emp_name=emp_name,
        emp_id=emp_id,
        emp_type=emp_type,
        dept=dept,
        designation=designation,
        profile_pic=profile_pic,
        agree_terms=agree_terms
    )

    return JsonResponse({
        "success": True,
        "employee_db_id": employee.id
    })


#--------------Face Record--------------------
def face_record(request, employee_db_id):
    employee = Employee.objects.filter(id=employee_db_id).first()
    if not employee:
        return HttpResponse("Employee not found", status=404)

    return render(
        request,
        "webapp/face_record.html",
        {
            "emp_name": employee.emp_name,
            "emp_id": employee.emp_id
        }
    )


def upload_face_video(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid method"})

    emp_id = request.POST.get("employee_id")
    file = request.FILES.get("video")

    if not emp_id or not file:
        return JsonResponse({"success": False, "error": "Missing data"})

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{emp_id}_{timestamp}.webm"

    upload_dir = os.path.join(settings.MEDIA_ROOT, "face_videos")
    os.makedirs(upload_dir, exist_ok=True)

    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb+") as dest:
        for chunk in file.chunks():
            dest.write(chunk)

    FaceRecording.objects.create(
        emp_id=emp_id,
        video_filename=filename,
        video_path=f"face_videos/{filename}"  #MEDIA serving
    )

    return JsonResponse({"success": True})


#--------------Recognized Faces--------------------
streams = {}

def camera_index(request):
    """
    Show available camera names
    """
    return render(
        request, 
        "webapp/camera_index.html", 
        {"camera_names": streams.keys()}
    )


def gen_frames(name):
    """
    Yield JPEG frames from running CameraWorker
    """
    try:
        worker = streams.get(name)
        if not worker:
            print(f"⚠️ No active stream found for '{name}'")
            return

        while True:
            frame_bytes = worker.get_jpeg()
            if not frame_bytes:
                time.sleep(0.05)
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + 
                frame_bytes + 
                b"\r\n"
            )

    except (BrokenPipeError, ConnectionResetError):
        print(f"🔌 [{name}] Client disconnected")
    except GeneratorExit:
        print(f"🧹 [{name}] Stream closed")
    except Exception as e:
        print(f"⚠️ [{name}] Stream error: {e}")


def video_feed(request, name):
    """
    Return MJPEG stream for a camera
    """
    if name not in streams:
        raise Http404("Camera not found")

    response = StreamingHttpResponse(
        gen_frames(name),
        content_type="multipart/x-mixed-replace; boundary=frame"
    )
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"

    print(f"🎥 [{name}] Stream started for {request.META.get('REMOTE_ADDR')}")
    return response     

#--------------Emp Tracking--------------------
def track_employee(request):
    
    mode = request.GET.get("mode")
    # mode = all | track | similar | unknown

    records = []
    results = []
    searched_emp_id = None
    searched_date = None
    searched_emp_name = None

    
    # SHOW ALL RECORDS
    if mode == "all":
        records = RecognizedFace.objects.all().order_by("-capture_date_time")

    # REVIEW SIMILAR
    elif mode == "similar":
        records = RecognizedFace.objects.filter(
            similarity_id__isnull=False
        ).order_by("-capture_date_time")

    # REVIEW UNKNOWN
    elif mode == "unknown":
        records = RecognizedFace.objects.filter(
            emp_id__isnull=True,
            similarity_id__isnull=True
        ).order_by("-capture_date_time")

   
    # TRACK EMPLOYEE
    today = date.today()           # or datetime.date.today()

    if request.method == "POST":
        emp_id = request.POST.get("emp_id")
        selected_date = request.POST.get("date")

        if emp_id and selected_date:
            try:
                date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()
            except ValueError:
                date_obj = today   # fallback if invalid date

            searched_emp_id = emp_id
            searched_date = date_obj
            
            emp = Employee.objects.filter(emp_id=emp_id).first()
            searched_emp_name = emp.emp_name if emp else "Unknown"
            
            qs = RecognizedFace.objects.filter(
                emp_id=emp_id,
                capture_date_time__date=date_obj
            ).order_by("capture_date_time")

            camera_map = {}
            for row in qs:
                camera_map.setdefault(row.camera_name, []).append(row)

            for cam_name, captures in camera_map.items():
                first = captures[0]
                last = captures[-1] if len(captures) > 1 else None

                results.append({
                    "camera_name": cam_name,
                    "first_time": first.capture_date_time,
                    "first_img": first.image_path,
                    "last_time": last.capture_date_time if last else None,
                })
            results = sorted(results, key=lambda x: x["last_time"] or x["first_time"])  
    return render(
        request,
        "webapp/track.html",
        {
            "records": records,
            "results": results,
            "mode": mode,
            "searched_emp_id": searched_emp_id,
            "searched_date": searched_date,
            "searched_emp_name": searched_emp_name,
            "today": today,
            "MEDIA_URL": settings.MEDIA_URL,
            "OS_TYPE": platform.system(),
        }
    )


#--------------Detected Face--------------------
def detected_faces(request):
    results = []
    searched = None
    today = date.today()

    cameras = (
        RecognizedFace.objects
        .annotate(cam=Trim("camera_name"))
        .values_list("cam", flat=True)
        .distinct()
        .order_by("cam")
    )

    if request.GET.get("date"):
        date_input = request.GET.get("date")
        camera = request.GET.get("camera")
        face_type = request.GET.get("type")
        
        if date_input:
            try:
                query_date = date.fromisoformat(date_input)
            except (ValueError, TypeError):
                query_date = today  # fallback on invalid date format
        else:
            query_date = today
        
        display_date = query_date.strftime("%Y-%m-%d")
        
        searched = {
        "date": display_date,
        "camera": "All Cameras" if camera == "all" else camera,
        "type": (
            "All Employees" if face_type == "employees" else
            "Unknown" if face_type == "unknown" else
            "All Types"
        ),
    }
    
        qs = RecognizedFace.objects.filter(
            capture_date_time__date=query_date
        ).exclude(similarity_id="NO_FACE")
        
        # 🔹 Collect all detected employee IDs
        emp_ids = (
            qs.filter(emp_id__isnull=False)
            .values_list("emp_id", flat=True)
            .distinct()
        )

        # 🔹 Build emp_id → emp_name map (single DB hit)
        emp_map = {
            e.emp_id: e.emp_name
            for e in Employee.objects.filter(emp_id__in=emp_ids, status="active")
        }

        if camera and camera != "all":
            qs = qs.filter(camera_name__icontains=camera)

        # 🔹 Type filter
        if face_type == "employees":
            qs = qs.filter(emp_id__isnull=False)

        elif face_type == "unknown":
            qs = qs.filter(similarity_id="UNKNOWN")

        else:
            qs = qs.filter(
                Q(emp_id__isnull=False) |
                Q(similarity_id="UNKNOWN")
            )

        qs = qs.order_by("-capture_date_time")

        track_map = {}   # ONLY for employees

        for r in qs:
            cam = r.camera_name.strip()

            #EMPLOYEE → group
            if r.emp_id:
                key = (cam, r.emp_id)

                if key not in track_map:
                    track_map[key] = {
                        "emp_id": r.emp_id,
                        "emp_name": emp_map.get(r.emp_id, ""),
                        "camera": cam,
                        "first_time": r.capture_date_time,
                        "last_time": None,
                        "image": r.image_path,
                    }
                else:
                    diff = (r.capture_date_time - track_map[key]["first_time"]).total_seconds()
                    if diff >= 600:
                        track_map[key]["last_time"] = r.capture_date_time

            # UNKNOWN → NO grouping
            else:
                results.append({
                    "emp_id": "UNKNOWN",
                    "emp_name": "",
                    "camera": cam,
                    "first_time": r.capture_date_time,
                    "last_time": None,   
                    "image": r.image_path,
                })

        # merge employee groups + unknown rows
        results = list(track_map.values()) + results
        results = sorted(results, key=lambda x: x["first_time"], reverse=True)

    return render(
        request,
        "webapp/detected_faces.html",
        {
            "results": results,
            "cameras": cameras,
            "searched": searched,
            "today": today,
            "MEDIA_URL": settings.MEDIA_URL,
            "OS_TYPE": platform.system(),
        }
    )

#--------------No Face--------------------
def no_face(request):
    results = []
    searched = None
    today = date.today()

    cameras = (
        RecognizedFace.objects
        .annotate(cam=Trim("camera_name"))
        .values_list("cam", flat=True)
        .distinct()
        .order_by("cam")
    )

    if request.GET.get("date"):
        date_input = request.GET.get("date")
        camera = request.GET.get("camera")
        
        if date_input:
            try:
                query_date = date.fromisoformat(date_input)
            except (ValueError, TypeError):
                query_date = today
        else:
            query_date = today

        searched = {
            "date": query_date.strftime("%Y-%m-%d"),
            "camera": camera if camera and camera != "all" else "All Cameras",
        }

        qs = RecognizedFace.objects.filter(
            similarity_id="NO_FACE",
            capture_date_time__date=query_date
        )

        if camera and camera != "all":
            qs = qs.filter(camera_name__icontains=camera)

        qs = qs.order_by("-capture_date_time", "-id")
        
        # NO grouping for NO_FACE
        for r in qs:
            results.append({
                "emp_id": "NO FACE",
                "camera": r.camera_name.strip(),
                "first_time": r.capture_date_time,
                "last_time": None,   
                "image": r.image_path,
            })

    return render(
        request,
        "webapp/no_face.html",
        {
            "results": results,
            "cameras": cameras,
            "searched": searched,
            "today": today,
            "MEDIA_URL": settings.MEDIA_URL,
            "OS_TYPE": platform.system(),
        }
    )


#--------------Employee List--------------------
def employee_list(request):
    query = request.GET.get("q", "").strip()

    employees = Employee.objects.filter(status="active").order_by("id")

    if query:
        employees = employees.filter(emp_id__icontains=query)

    return render(request, "webapp/employee_list.html", {
        "employees": employees,
        "query": query
    })


#--------------Employee Edit--------------------
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == "POST":
        employee.emp_name = request.POST.get("emp_name")
        employee.dept = request.POST.get("dept")
        employee.emp_type = request.POST.get("emp_type")

        if request.FILES.get("profile_pic"):
            employee.profile_pic = request.FILES.get("profile_pic")

        employee.save()
        return redirect("employee_list")

    return render(request, "webapp/employee_edit.html", {
        "employee": employee
    })

#--------------Employee Delete--------------------
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    employee.status = "inactive"
    employee.save()
    return redirect("employee_list")


#--------------Attenadace--------------------
def attendance_page(request):
    date_str = request.GET.get("date")

    # ✅ If no date selected → use today's date
    if not date_str:
        selected_date = date.today()
        date_str = selected_date.strftime("%Y-%m-%d")
    else:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    start_dt = datetime.combine(selected_date, datetime.min.time())
    end_dt   = datetime.combine(selected_date, datetime.max.time())

    attendance = []

    records = (
        RecognizedFace.objects
        .filter(
            capture_date_time__range=(start_dt, end_dt),
            emp_id__isnull=False
        )
        .exclude(emp_id__in=["", "UNKNOWN", "NO_FACE"])
        .order_by("emp_id", "capture_date_time")
    )

    emp_map = {}

    for r in records:
        emp_map.setdefault(r.emp_id, []).append(r)

    for emp_id, recs in emp_map.items():
        first = recs[0]
        last  = recs[-1]

        employee = Employee.objects.filter(emp_id=emp_id).first()
        emp_name = employee.emp_name if employee else "-"

        check_out_time = None
        check_out_cam = None
        total_hours = "-"

        if len(recs) > 1:
            check_out_time = last.capture_date_time
            check_out_cam = last.camera_name
            total_hours = str(last.capture_date_time - first.capture_date_time).split(".")[0]

        attendance.append({
            "emp_id": emp_id,
            "emp_name": emp_name,
            #"image": f"/media/{first.image_path}",
            "image": first.image_path,
            "check_in_time": first.capture_date_time,
            "check_in_cam": first.camera_name,
            "check_out_time": check_out_time,
            "check_out_cam": check_out_cam,
            "total_hours": total_hours,
        })

    return render(request, "webapp/attendance.html", {
        "attendance": attendance,
        "selected_date": date_str,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(),
    })


def login_view(request):

    today = str(date.today())  

    # check if already logged in today
    if request.session.get("login_date") == today:
        return redirect("create_rule")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if username == "admin" and password == "admin@123":
            request.session["logged_in"] = True
            request.session["login_date"] = today   # store today's date
            return redirect("create_rule")

        return render(request, "webapp/login.html", {
            "error": "Invalid username or password"
        })

    return render(request, "webapp/login.html")


# ---------------- CREATE RULE (STEP 1: ONLY BOX UI) ----------------
def create_rule(request):

    today = str(date.today())

    if request.session.get("login_date") != today:
        return redirect("login")

    return render(request, "webapp/create_rule.html")

#---------------------MEETING RULE----------------------------
def create_meeting_rule(request):
    # get or create meeting rule row
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="meeting",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    # ---------- SAVE ----------
    if request.method == "POST":
        rule_no = f"rule_{len(rules) + 1}"

        rules[rule_no] = {
            "date": request.POST.get("date"),
            "start_time": request.POST.get("start_time"),
            "end_time": request.POST.get("end_time"),
            "department": request.POST.getlist("department"),
            "place": request.POST.getlist("place"),
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true"
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_meeting_rule")

    # ---------- DROPDOWNS ----------
    departments = (
        Employee.objects
        .values_list("dept", flat=True)
        .distinct()
        .order_by("dept")
    )

    # camera names (NO duplicates)
    from webapp.views import streams
    cameras = list(streams.keys())
    
    #FETCH MEETING RECORDS FROM DATABASE
    meeting_records = EmailSend.objects.filter(
        rule_category="Meeting Rule"
    ).order_by("-created_at")

    return render(request, "webapp/create_meeting_rule.html", {
        "departments": departments,
        "cameras": cameras,
        "rules": rules,
        "meeting_records": meeting_records,
        "MEDIA_URL": settings.MEDIA_URL ,
        "OS_TYPE": platform.system(),
    })

def toggle_meeting_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="meeting")
    rules = rule_obj.rules_json

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key]["active"]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_meeting_rule")

def delete_meeting_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="meeting")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_meeting_rule")

#----------------ALLOWED PLACE RULE------------------
def create_allowed_place_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="allowed_place",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rule_no = f"rule_{len(rules) + 1}"

        rules[rule_no] = {
            "department": request.POST.getlist("department"),  
            "place": request.POST.getlist("place"),
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true",
            
            "time_mode": request.POST.get("time_mode"),
            "start_time": request.POST.get("start_time"),
            "end_time": request.POST.get("end_time"),
            "zone_type": request.POST.get("zone_type")
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_allowed_place_rule")

    departments = Employee.objects.values_list("dept", flat=True).distinct()
   
    cameras = list(streams.keys())

    return render(request, "webapp/create_allowed_place_rule.html", {
        "departments": departments,
        "cameras": cameras,
        "rules": rules
    })

def toggle_allowed_place_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="allowed_place")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_allowed_place_rule")

def delete_allowed_place_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="allowed_place")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_allowed_place_rule")


#----------------RESTRICTED ZONE RULE------------------
def create_restricted_zone_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="restricted_zone",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rule_no = f"rule_{len(rules) + 1}"

        rules[rule_no] = {
            "restricted_departments": request.POST.getlist("department"),
            "place": request.POST.getlist("place"),
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true",

            # NEW TIME FIELDS
            "time_mode": request.POST.get("time_mode"),
            "start_time": request.POST.get("start_time"),
            "end_time": request.POST.get("end_time"),
            "zone_type": request.POST.get("zone_type"), 
        }


        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_restricted_zone_rule")

    departments = Employee.objects.values_list("dept", flat=True).distinct()
  
    cameras = list(streams.keys())

    return render(request,"webapp/create_restricted_zone_rule.html",{
        "departments":departments,
        "cameras":cameras,
        "rules":rules
    })

def toggle_restricted_zone_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="restricted_zone")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_restricted_zone_rule")


def delete_restricted_zone_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="restricted_zone")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_restricted_zone_rule")


#----------------IN/OUT TIME RULE------------------
def create_inout_time_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="inout_time",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rule_no = f"rule_{len(rules) + 1}"

        # 🔁 MULTIPLE BREAKS
        breaks = []
        break_names = request.POST.getlist("break_name[]")
        break_starts = request.POST.getlist("break_start[]")
        break_ends = request.POST.getlist("break_end[]")
        break_places = request.POST.getlist("break_place[]")

        for i in range(len(break_names)):
            breaks.append({
                "name": break_names[i],
                "start": break_starts[i],
                "end": break_ends[i],
                "place": break_places[i].split(",")
            })

        rules[rule_no] = {
            "attendance": {
                "in_before": request.POST.get("in_before"),
                "out_after": request.POST.get("out_after"),
                "place": request.POST.getlist("attendance_place[]"),
            },

            "breaks": breaks,
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true"
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_inout_time_rule")

    from webapp.views import streams
    cameras = list(streams.keys())

    return render(request, "webapp/create_inout_time_rule.html", {
        "rules": rules,
        "cameras": cameras
    })


def toggle_inout_time_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="inout_time")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key]["active"]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_inout_time_rule")


def delete_inout_time_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="inout_time")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_inout_time_rule")

#-----------------UNKNOW PERSON ALERT-------------------
def create_unknown_alert_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="unknown_alert",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rules["rule_1"] = {
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true"
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_unknown_alert_rule")
    
    unknown_records = EmailSend.objects.filter(
        rule_category="Unknown Person"
    ).order_by("-created_at")

    return render(request, "webapp/create_unknown_alert_rule.html", {
        "rule": rules.get("rule_1"),
        "unknown_records": unknown_records,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(), 
    })


def toggle_unknown_alert_rule(request):
    rule_obj = Rule.objects.get(rule_type="unknown_alert")
    rules = rule_obj.rules_json or {}

    rules["rule_1"]["active"] = not rules["rule_1"]["active"]

    rule_obj.rules_json = rules
    rule_obj.save()

    return redirect("create_unknown_alert_rule")

def delete_unknown_alert_rule(request):
    try:
        rule_obj = Rule.objects.get(rule_type="unknown_alert")
    except Rule.DoesNotExist:
        return redirect("create_unknown_alert_rule")

    rule_obj.rules_json = {}   # 🔥 clear rule
    rule_obj.save()

    return redirect("create_unknown_alert_rule")

#-----------------PHONE USAGE ALERT-------------------
def create_phone_usage_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="phone_usage",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rule_no = f"rule_{len(rules) + 1}"

        rules[rule_no] = {
            "place": request.POST.getlist("place"),   # multi camera
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true"
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_phone_usage_rule")

    cameras = list(streams.keys())

    return render(request, "webapp/phone_usage_rule.html", {
        "rules": rules,
        "cameras": cameras
    })

def toggle_phone_usage_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="phone_usage")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_phone_usage_rule")

def delete_phone_usage_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="phone_usage")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_phone_usage_rule")

#-----------------SAFETY RULE-------------------
def create_helmet_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(
        rule_type="helmet",
        defaults={"rules_json": {}}
    )

    rules = rule_obj.rules_json or {}

    if request.method == "POST":
        rule_key = f"rule_{len(rules)+1}"

        rules[rule_key] = {
            "place": request.POST.getlist("place"),
            "head_email": request.POST.get("head_email"),
            "active": request.POST.get("active") == "true"
        }

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_helmet_rule")

    cameras = list(streams.keys())

    return render(request, "webapp/create_helmet_rule.html", {
        "rules": rules,
        "cameras": cameras
    })


def toggle_helmet_rule(request, rule_key):
    r = Rule.objects.get(rule_type="helmet")
    rules = r.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        r.rules_json = rules
        r.save()

    return redirect("create_helmet_rule")



def delete_helmet_rule(request, rule_key):
    r = Rule.objects.get(rule_type="helmet")
    rules = r.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        r.rules_json = rules
        r.save()

    return redirect("create_helmet_rule")



#--------------Rule dashboard--------------------------
def violation_dashboard(request):
    
    # Base queryset
    records = EmailSend.objects.exclude(
    rule_category__icontains="meeting"
    ).exclude(
        rule_category__icontains="unknown"
    ).exclude(
        rule_category__icontains="group"
    ).exclude(   # ✅ ADD THIS
        rule_category__icontains="no employee"
    ).order_by("-created_at")

    # ─── Filters ───
    rule      = request.GET.get("rule_type")
    employee  = request.GET.get("employee")
    date_from = request.GET.get("date_from")
    date_to   = request.GET.get("date_to")

    if rule:
        rule = rule.lower()
        if rule == "restricted":
            records = records.filter(rule_category__icontains="restricted")
        elif rule == "allowed":
            records = records.filter(rule_category__icontains="allowed")
        elif rule in ("inout", "in/out"):
            records = records.filter(rule_category__icontains="inout") | \
                      records.filter(rule_category__icontains="in/out")
        elif rule == "phone":
            records = records.filter(rule_category__icontains="phone")
        elif rule == "safety":
            records = records.filter(rule_category__icontains="safety")

    if employee:
        records = records.filter(
            Q(employee_id__icontains=employee) |
            Q(employee_name__icontains=employee)
        )

    if date_from:
        records = records.filter(created_at__date__gte=date_from)

    if date_to:
        records = records.filter(created_at__date__lte=date_to)
        
    
    # ================= 🔥 ADD THIS BLOCK 🔥 =================
    unauth_only = request.GET.get("unauth_only")

    if unauth_only == "true":
        # 🔴 ALL unauthorized (UNKNOWN, NO_FACE, TX001...)
        records = records.filter(unauthorized_person__isnull=False)

    else:
        # 🟢 ONLY employees (no unauthorized_person)
        records = records.filter(unauthorized_person__isnull=True)
        
    

    # ─── Dynamic page size ───
    page_size_str = request.GET.get("page_size", "50")

    try:
        per_page = int(page_size_str)
        # Safety limits
        if per_page < 5:
            per_page = 5
        if per_page > 500:
            per_page = 500
    except (ValueError, TypeError):
        per_page = 50

    # Create paginator with the actual requested size
    paginator = Paginator(records, per_page)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "webapp/violation_dashboard.html", {
        "page_obj": page_obj,
        "current_page_size": per_page,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(),
    })

from xhtml2pdf import pisa
from django.template.loader import get_template
from django.http import HttpResponse
import os
from django.conf import settings


def export_violation_pdf(request):

    records = EmailSend.objects.exclude(
        rule_category__icontains="meeting"
    ).exclude(
        rule_category__icontains="unknown"
    ).exclude(
        rule_category__icontains="group"
    ).order_by("-created_at")

    # filters (same as before)
    rule = request.GET.get("rule_type")
    employee = request.GET.get("employee")
    df = request.GET.get("date_from")
    dt = request.GET.get("date_to")

    if rule:
        records = records.filter(rule_category__icontains=rule)

    if employee:
        records = records.filter(
            Q(employee_id__icontains=employee) |
            Q(employee_name__icontains=employee)
        )

    if df:
        records = records.filter(created_at__date__gte=df)

    if dt:
        records = records.filter(created_at__date__lte=dt)

    # 🔥 template render
    template = get_template("webapp/pdf_template.html")
    html = template.render({
        "records": records,
        "MEDIA_ROOT": settings.MEDIA_ROOT, 
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Unauthorized_entry.pdf"'

    pisa.CreatePDF(html, dest=response)

    return response


# ================= CAMERA BOUNDARY MANAGEMENT =================
from webapp.models import CameraBoundary
import json
from urllib.parse import urlencode

def get_camera_boundaries(request):
    camera = request.GET.get('camera')
    if not camera:
        return JsonResponse({'boundaries': []})
    boundaries = CameraBoundary.objects.filter(camera_name=camera)
    data = [{'name': b.boundary_name, 'points': b.points} for b in boundaries]
    return JsonResponse({'boundaries': data})

def save_camera_boundary(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    try:
        data = json.loads(request.body)
        camera_name = data.get('camera_name')
        boundary_name = data.get('boundary_name')
        points = data.get('points')
        if not all([camera_name, boundary_name, points]) or len(points) != 4:
            return JsonResponse({'success': False, 'error': 'Invalid data'})
        points = [[int(p[0]), int(p[1])] for p in points]
        obj, created = CameraBoundary.objects.update_or_create(
            camera_name=camera_name,
            boundary_name=boundary_name,
            defaults={'points': points}
        )
        return JsonResponse({'success': True, 'created': created})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def delete_camera_boundary(request):
    if request.method != 'POST':
        return JsonResponse({'success': False})
    try:
        data = json.loads(request.body)
        camera_name = data.get('camera_name')
        boundary_name = data.get('boundary_name')
        CameraBoundary.objects.filter(camera_name=camera_name, boundary_name=boundary_name).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def camera_boundary_editor(request, camera_name):
    """Render the boundary drawing editor for a specific camera (standalone)"""
    return render(request, 'webapp/camera_boundary_editor_standalone.html', {'camera_name': camera_name})
    
def get_frame_for_camera_boundary(request):
    camera = request.GET.get('camera')
    if not camera or camera not in streams:
        return HttpResponse(status=404)
    worker = streams.get(camera)
    frame_bytes = worker.get_jpeg()
    if frame_bytes:
        return HttpResponse(frame_bytes, content_type='image/jpeg')
    return HttpResponse(status=500)

# ================= NO EMPLOYEE SHIFT =================
from .models import NoEmployeeShift
from django.utils import timezone
def no_employee_shift(request):

    if request.method == "POST":

        shift_name = request.POST.get("shift_name")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        NoEmployeeShift.objects.create(
            shift_name=shift_name,
            start_time=start_time,
            end_time=end_time
        )

        return redirect("no_employee_shift")

    shifts = NoEmployeeShift.objects.all().order_by("start_time")

    return render(
        request,
        "webapp/no_employee_shift.html",
        {
            "shifts": shifts
        }
    )
    
def edit_no_employee_shift(request, id):

    shift = NoEmployeeShift.objects.get(id=id)

    if request.method == "POST":

        shift.shift_name = request.POST.get("shift_name")
        shift.start_time = request.POST.get("start_time")
        shift.end_time = request.POST.get("end_time")

        shift.save()

        return redirect("no_employee_shift")

    shifts = NoEmployeeShift.objects.all().order_by("start_time")

    return render(
        request,
        "webapp/no_employee_shift.html",
        {
            "edit_shift": shift,
            "shifts": shifts
        }
    )

def delete_no_employee_shift(request, id):

    NoEmployeeShift.objects.filter(id=id).delete()

    return redirect("no_employee_shift")


# ================= NO EMPLOYEE RULE =================   
def create_no_employee_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(rule_type="no_employee", defaults={"rules_json": {}})
    rules = rule_obj.rules_json or {}

    edit_rule_key = request.GET.get('edit_rule')
    selected_cameras = []
    selected_boundaries_per_camera = {}
    form_data = {}
    current_rule_key = None

    if edit_rule_key and edit_rule_key in rules:
        rule_data = rules[edit_rule_key]
        selected_cameras = rule_data.get("cameras", [])
        selected_boundaries_per_camera = rule_data.get("boundaries", {})
        form_data = {
            "alert_duration": rule_data.get("duration_minutes", ""),
            "min_count": rule_data.get("min_count", ""),
            "break_start": rule_data.get("break_start", ""),
            "break_end": rule_data.get("break_end", ""),
            "email": rule_data.get("head_email", ""),
            "active": "true" if rule_data.get("active", False) else "false",
        }
        current_rule_key = edit_rule_key

    # ---------- SAVE RULE (CREATE OR UPDATE) ----------
    if request.method == "POST":
        cameras = request.POST.getlist("cameras")
        min_count = request.POST.get("min_count")
        duration = request.POST.get("alert_duration")
        email = request.POST.get("email")
        break_start = request.POST.get("break_start")
        break_end = request.POST.get("break_end")
        active = request.POST.get("active") == "true"
        edit_key = request.POST.get("edit_rule_key")

        # ---------- VALIDATION ----------
        errors = []
        if not cameras:
            errors.append("Please select at least one camera.")
        if not min_count or min_count == '':
            errors.append("Min Count is required.")
        if not duration or duration == '':
            errors.append("Alert Duration is required.")
        if not email or email == '':
            errors.append("Head Email is required.")
        
        if errors:
            # Re-render form with errors (you can add an error display div in template)
            cameras_list = list(streams.keys())
            shifts = NoEmployeeShift.objects.all().order_by("start_time")
            return render(request, "webapp/create_no_employee_rule.html", {
                "cameras": cameras_list,
                "rules": rules,
                "page_obj": page_obj,  # You need to define page_obj – better to reuse the existing logic below
                "selected_cameras": cameras,
                "selected_boundaries_per_camera": {},
                "form_data": request.POST,
                "rule_key": edit_key,
                "query_string": "",
                "MEDIA_URL": settings.MEDIA_URL,
                "OS_TYPE": platform.system(),
                "shifts": shifts,
                "error_message": " | ".join(errors),
            })
        
        # Collect boundaries
        boundaries_per_camera = {}
        for cam in cameras:
            boundaries_param = request.POST.get(f"boundaries_{cam}", "")
            boundaries_per_camera[cam] = boundaries_param.split(',') if boundaries_param else []

        if edit_key and edit_key in rules:
            # Update existing rule
            rules[edit_key].update({
                "cameras": cameras,
                "min_count": min_count,
                "duration_minutes": duration,
                "head_email": email,
                "break_start": break_start,
                "break_end": break_end,
                "active": active,
                "boundaries": boundaries_per_camera
            })
            print(f"✏️ Updated rule '{edit_key}'")
        else:
            # Create new rule
            rule_number = 1

            while f"rule_{rule_number}" in rules:
                rule_number += 1

            new_rule_key = f"rule_{rule_number}"
            
            rules[new_rule_key] = {
                "cameras": cameras,
                "min_count": min_count,
                "duration_minutes": duration,
                "head_email": email,
                "break_start": break_start,
                "break_end": break_end,
                "active": active,
                "boundaries": boundaries_per_camera
            }
            #print(f"✨ Created new rule '{new_rule_key}'")

        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_no_employee_rule")

    # ---------- GET: Show form and existing rules ----------
    records = EmailSend.objects.filter(rule_category__icontains="no employee").order_by("-created_at")
    place = request.GET.get("place")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    shift_filter = request.GET.get("shift")
    if place:
        records = records.filter(place__icontains=place)
    if date_from:
        records = records.filter(created_at__date__gte=date_from)
    if date_to:
        records = records.filter(created_at__date__lte=date_to)
    if shift_filter and shift_filter != "All":
        records = records.filter(shift_name=shift_filter)
        
    # ---------- ADD HERE ----------
    total_no_employee_minutes = 0

    for rec in records:

        if not rec.time:
            continue

        try:

            start_str, end_str = [x.strip() for x in rec.time.split("-")]

            start_dt = datetime.strptime(start_str, "%H:%M")
            end_dt = datetime.strptime(end_str, "%H:%M")

            diff = (end_dt - start_dt).seconds // 60

            total_no_employee_minutes += diff

        except Exception as e:
            print("Time Parse Error:", e)
        
    # ---------- NEXT ADD working_minutes CODE ----------
    working_minutes = 0

    all_shifts = NoEmployeeShift.objects.all()

    for shift in all_shifts:

        start_dt = datetime.combine(
            datetime.today(),
            shift.start_time
        )

        end_dt = datetime.combine(
            datetime.today(),
            shift.end_time
        )

        working_minutes += int(
            (end_dt - start_dt).total_seconds() / 60
        )
            
            
    # ---------- ADD HERE ----------
    employee_minutes = max(
        working_minutes - total_no_employee_minutes,
        0
    )

    # ---------- chart 1 ----------

    working_hours_text = (
        f"{working_minutes // 60} hr "
        f"{working_minutes % 60} min"
    )

    no_employee_text = (
        f"{total_no_employee_minutes // 60} hr "
        f"{total_no_employee_minutes % 60} min"
    )

    employee_text = (
        f"{employee_minutes // 60} hr "
        f"{employee_minutes % 60} min"
    )
    
    # ---------- day/month chart 2----------
    shift1_minutes = 0
    shift2_minutes = 0
    shift3_minutes = 0

    chart_type = request.GET.get("chart_type", "day")
    if chart_type == "month":

        chart_records = EmailSend.objects.filter(
            rule_category__icontains="no employee",
            created_at__year=timezone.now().year,
            created_at__month=timezone.now().month
        )

    else:

        chart_records = EmailSend.objects.filter(
            rule_category__icontains="no employee",
            created_at__date=timezone.now().date()
        )

    for rec in chart_records:

        if not rec.time:
            continue

        try:

            start_str, end_str = [x.strip() for x in rec.time.split("-")]

            start_dt = datetime.strptime(start_str, "%H:%M")
            end_dt = datetime.strptime(end_str, "%H:%M")

            mins = (end_dt - start_dt).seconds // 60

            shift_name = (rec.shift_name or "").strip()

            if shift_name == "Shift I":
                shift1_minutes += mins

            elif shift_name == "Shift II":
                shift2_minutes += mins

            elif shift_name == "Shift III":
                shift3_minutes += mins

        except:
            pass


   
    per_page = request.GET.get("per_page", 10)
    try:
        per_page = int(per_page)
    except:
        per_page = 10
    paginator = Paginator(records, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    from urllib.parse import urlencode
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = urlencode(query_params)

    cameras = list(streams.keys())
    shifts = NoEmployeeShift.objects.all().order_by("start_time")
    current_date = datetime.now().strftime("%d/%m/%Y")
    current_month = datetime.now().strftime("%B %Y")
    
    return render(request, "webapp/create_no_employee_rule.html", {
        "cameras": cameras,
        "rules": rules,
        "page_obj": page_obj,
        "selected_cameras": selected_cameras,
        "selected_boundaries_per_camera": selected_boundaries_per_camera,
        "form_data": form_data,
        "rule_key": current_rule_key,
        "query_string": query_string,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(),
        "shifts": shifts,
        
        "working_hours_text": working_hours_text,
        "no_employee_text": no_employee_text,
        "employee_text": employee_text,
        "working_minutes": working_minutes,
        "no_employee_minutes": total_no_employee_minutes,
        "employee_minutes": employee_minutes,
        "selected_shift": shift_filter,
        "shift1_minutes": shift1_minutes,
        "shift2_minutes": shift2_minutes,
        "shift3_minutes": shift3_minutes,
        "chart_type": chart_type,
        "current_date": current_date,
        "current_month": current_month,
    })
    
    
def toggle_no_employee_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="no_employee")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_no_employee_rule")

def delete_no_employee_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="no_employee")
    rules = rule_obj.rules_json or {}

    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()

    return redirect("create_no_employee_rule")


def export_no_employee_pdf(request):

    records = EmailSend.objects.filter(
        rule_category__icontains="no employee"
    )

    for r in records:
        if r.image_path:
             r.image_path = r.image_path.split("recognized_cctv\\")[-1]

    template = get_template("webapp/no_employee_pdf.html")

    html = template.render({
        "records": records,
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="no_employee.pdf"'

    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response

def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those resources
    """
    if uri.startswith('/media/'):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace('/media/', ''))
    elif uri.startswith('/static/'):
        path = os.path.join(settings.STATIC_ROOT, uri.replace('/static/', ''))
    else:
        return uri

    if not os.path.isfile(path):
        raise Exception(f'Media URI must start with /media/ or /static/. Got {uri}')

    return path




# ================= GROUP RULE =================
import base64
from PIL import Image
import io

def create_group_rule(request):
    rule_obj, _ = Rule.objects.get_or_create(rule_type="group", defaults={"rules_json": {}})
    rules = rule_obj.rules_json or {}

    # Editing existing rule
    edit_rule_key = request.GET.get('edit_rule')
    selected_cameras = []
    form_data = {}
    current_rule_key = None

    if edit_rule_key and edit_rule_key in rules:
        rule_data = rules[edit_rule_key]
        selected_cameras = list(rule_data.get("cameras", {}).keys())
        form_data = {
            "alert_duration": rule_data.get("duration_minutes", ""),
            "max_count": rule_data.get("max_count", ""),
            "group_distance": rule_data.get("group_distance", ""),
            "break_start": rule_data.get("break_start", ""),
            "break_end": rule_data.get("break_end", ""),
            "email": rule_data.get("head_email", ""),
            "active": "true" if rule_data.get("active", False) else "false",
        }
        current_rule_key = edit_rule_key

    # ---------- SAVE (CREATE OR UPDATE) ----------
    if request.method == "POST":
        cameras = request.POST.getlist("cameras")
        max_count = request.POST.get("max_count")
        duration = request.POST.get("alert_duration")
        email = request.POST.get("email")
        break_start = request.POST.get("break_start")
        break_end = request.POST.get("break_end")
        active = request.POST.get("active") == "true"
        group_distance = request.POST.get("group_distance")
        edit_key = request.POST.get("edit_rule_key")

        # Validation
        errors = []
        if not cameras:
            errors.append("At least one camera must be selected.")
        if not max_count:
            errors.append("Max Allowed People is required.")
        if not duration:
            errors.append("Alert Duration is required.")
        if not email:
            errors.append("Head Email is required.")
        if not group_distance:
            errors.append("Group Distance is required.")
        if errors:
            # Re-render with error message (you can pass error_message to template)
            cameras_list = list(streams.keys())
            return render(request, "webapp/create_group_rule.html", {
                "cameras": cameras_list,
                "rules": rules,
                "page_obj": Paginator(EmailSend.objects.filter(rule_category="Group Rule").order_by("-created_at"), 10).get_page(1),
                "selected_cameras": cameras,
                "form_data": request.POST,
                "edit_rule_key": edit_key,
                "error_message": " | ".join(errors),
                "MEDIA_URL": settings.MEDIA_URL,
                "OS_TYPE": platform.system(),
            })

        camera_eps = {cam: 1.0 for cam in cameras}

        if edit_key and edit_key in rules:
            # Update existing rule
            rules[edit_key] = {
                "cameras": camera_eps,
                "max_count": int(max_count) if max_count else 2,
                "duration_minutes": float(duration) if duration else 1,
                "head_email": email,
                "break_start": break_start or "",
                "break_end": break_end or "",
                "active": active,
                "group_distance": float(group_distance) if group_distance else 1.0,
            }
        else:
            # Create new rule
            new_rule_key = f"rule_{len(rules) + 1}"
            rules[new_rule_key] = {
                "cameras": camera_eps,
                "max_count": int(max_count) if max_count else 2,
                "duration_minutes": float(duration) if duration else 1,
                "head_email": email,
                "break_start": break_start or "",
                "break_end": break_end or "",
                "active": active,
                "group_distance": float(group_distance) if group_distance else 1.0,
            }
        rule_obj.rules_json = rules
        rule_obj.save()
        return redirect("create_group_rule")

    # ---------- GET: display form and records ----------
    records = EmailSend.objects.filter(rule_category="Group Rule").order_by("-created_at")
    place = request.GET.get("place")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    if place:
        records = records.filter(place__icontains=place)
    if date_from:
        records = records.filter(created_at__date__gte=date_from)
    if date_to:
        records = records.filter(created_at__date__lte=date_to)

    per_page = request.GET.get("per_page", 50)
    try:
        per_page = int(per_page)
    except:
        per_page = 50
    paginator = Paginator(records, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    cameras = list(streams.keys())

    return render(request, "webapp/create_group_rule.html", {
        "cameras": cameras,
        "rules": rules,
        "page_obj": page_obj,
        "selected_cameras": selected_cameras,
        "form_data": form_data,
        "edit_rule_key": current_rule_key,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(),
    })


def toggle_group_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="group")
    rules = rule_obj.rules_json or {}
    if rule_key in rules:
        rules[rule_key]["active"] = not rules[rule_key].get("active", False)
        rule_obj.rules_json = rules
        rule_obj.save()
    return redirect("create_group_rule")


def delete_group_rule(request, rule_key):
    rule_obj = Rule.objects.get(rule_type="group")
    rules = rule_obj.rules_json or {}
    if rule_key in rules:
        del rules[rule_key]
        rule_obj.rules_json = rules
        rule_obj.save()
    return redirect("create_group_rule")


def export_group_pdf(request):
    # Apply same filters as the main view
    records = EmailSend.objects.filter(rule_category="Group Rule").order_by("-created_at")
    
    # Apply filters from request.GET
    place = request.GET.get("place")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    
    if place:
        records = records.filter(place__icontains=place)
    if date_from:
        records = records.filter(created_at__date__gte=date_from)
    if date_to:
        records = records.filter(created_at__date__lte=date_to)
    
    # Process each record: compress image and convert to base64
    for r in records:
        if r.image_path:
            try:
                # Build absolute path to image
                import platform
                if platform.system() == "Windows":
                    img_path = Path(settings.BASE_DIR) / r.image_path
                else:
                    img_path = Path(settings.MEDIA_ROOT) / r.image_path
                
                if img_path.exists():
                    # Open image, compress, and convert to base64
                    with Image.open(img_path) as img:
                        # Convert to RGB if needed (for PNG with transparency)
                        if img.mode in ('RGBA', 'LA', 'P'):
                            img = img.convert('RGB')
                        # Resize if too large (max width 300px)
                        if img.width > 300:
                            ratio = 300 / img.width
                            new_size = (300, int(img.height * ratio))
                            img = img.resize(new_size, Image.Resampling.LANCZOS)
                        # Save to bytes with 60% quality
                        buffer = io.BytesIO()
                        img.save(buffer, format='JPEG', quality=60, optimize=True)
                        r.image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                else:
                    r.image_base64 = ''
            except Exception as e:
                print(f"Image compression error: {e}")
                r.image_base64 = ''
        else:
            r.image_base64 = ''

    template = get_template("webapp/group_pdf.html")
    html = template.render({"records": records})
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="group_rule.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response


# ================= WORK DETECTION RULE =================
from django.contrib import messages
def create_work_rule(request):
    
    edit_rule_key = request.GET.get('edit_rule')
    
    cameras = list(views.streams.keys()) if hasattr(views, 'streams') else []
    
    # Get camera boundaries
    camera_boundaries = {}
    for cam in cameras:
        boundaries = CameraBoundary.objects.filter(camera_name=cam)
        camera_boundaries[cam] = [b.boundary_name for b in boundaries]
    
    existing_rules = {}
    form_data = {}
    selected_cameras = []
    selected_boundaries_per_camera = {}
    
    try:
        rule_obj = Rule.objects.get(rule_type="work")
        existing_rules = rule_obj.rules_json or {}
        
        if edit_rule_key and edit_rule_key in existing_rules:
            rule_data = existing_rules[edit_rule_key]
            form_data = {
                'email': rule_data.get('email', ''),
                'min_count': rule_data.get('min_count', 1),
                'duration_minutes': rule_data.get('duration_minutes', 5),
                'work_schedules': rule_data.get('work_schedules', [{'start': '09:00', 'end': '13:00'}]),
                'active': 'true' if rule_data.get('active', True) else 'false',
            }
            selected_cameras = rule_data.get('cameras', [])
            selected_boundaries_per_camera = rule_data.get('boundaries', {})
    except Rule.DoesNotExist:
        pass
    
    if request.method == 'POST':
        try:
            # Get form data
            edit_key = request.POST.get('edit_rule_key')
            email = request.POST.get('email')
            min_count = int(request.POST.get('min_count', 1))
            duration_minutes = int(request.POST.get('duration_minutes', 5))
            cameras_selected = request.POST.getlist('cameras')
            active = request.POST.get('active') == 'true'
            
            # Get work schedules
            work_starts = request.POST.getlist('work_start[]')
            work_ends = request.POST.getlist('work_end[]')
            work_schedules = []
            for i in range(len(work_starts)):
                if i < len(work_ends):
                    work_schedules.append({
                        'start': work_starts[i],
                        'end': work_ends[i]
                    })
            
            # Get boundaries per camera
            boundaries = {}
            for cam in cameras_selected:
                boundary_key = f'boundaries_{cam}'
                boundary_values = request.POST.get(boundary_key, '')
                if boundary_values:
                    boundaries[cam] = boundary_values.split(',')
                else:
                    boundaries[cam] = []
            
            # Generate rule key
            if edit_key:
                rule_key = edit_key
            else:
                import uuid
                rule_key = f"work_{uuid.uuid4().hex[:8]}"
            
            # Load existing rules
            try:
                rule_obj = Rule.objects.get(rule_type="work")
                rules_data = rule_obj.rules_json or {}
            except Rule.DoesNotExist:
                rule_obj = Rule.objects.create(rule_type="work", rules_json={})
                rules_data = {}
            
            # Save rule
            rules_data[rule_key] = {
                'email': email,
                'min_count': min_count,
                'duration_minutes': duration_minutes,
                'work_schedules': work_schedules,
                'cameras': cameras_selected,
                'boundaries': boundaries,
                'active': active,
                'created_at': datetime.now().isoformat()
            }
            
            rule_obj.rules_json = rules_data
            rule_obj.save()
            
            messages.success(request, f'Work rule "{rule_key}" saved successfully!')
            return redirect('create_work_rule')
            
        except Exception as e:
            messages.error(request, f'Error saving rule: {str(e)}')
            return redirect('create_work_rule')
    
    
    # Filter parameters
    place_filter = request.GET.get('place', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    per_page = int(request.GET.get('per_page', 50))
    page = int(request.GET.get('page', 1))
    
    queryset = EmailSend.objects.filter(rule_category="Work Rule").order_by('-created_at')
    
    if place_filter:
        queryset = queryset.filter(place__icontains=place_filter)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page)
    
    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    query_string = query_params.urlencode()
    
    context = {
        'rules': existing_rules,
        'cameras': cameras,
        'camera_boundaries': camera_boundaries,
        'form_data': form_data,
        'selected_cameras': selected_cameras,
        'selected_boundaries_per_camera': selected_boundaries_per_camera,
        'rule_key': edit_rule_key,
        'page_obj': page_obj,
        'query_string': query_string,
        'MEDIA_URL': settings.MEDIA_URL,
        'OS_TYPE': 'Windows' if os.name == 'nt' else 'Linux',
    }
    return render(request, 'webapp/create_work_rule.html', context)


def toggle_work_rule(request, rule_key):
    try:
        rule_obj = Rule.objects.get(rule_type="work")
        rules = rule_obj.rules_json
        
        if rule_key in rules:
            rules[rule_key]['active'] = not rules[rule_key].get('active', True)
            rule_obj.rules_json = rules
            rule_obj.save()
            
            status = "activated" if rules[rule_key]['active'] else "deactivated"
            messages.success(request, f'Work rule "{rule_key}" {status}!')
        else:
            messages.error(request, "Rule not found!")
    except Rule.DoesNotExist:
        messages.error(request, "No work rules found!")
    
    return redirect('create_work_rule')


def delete_work_rule(request, rule_key):
    
    if request.method == 'POST':
        try:
            rule_obj = Rule.objects.get(rule_type="work")
            rules = rule_obj.rules_json
            
            if rule_key in rules:
                del rules[rule_key]
                rule_obj.rules_json = rules
                rule_obj.save()
                messages.success(request, f'Work rule "{rule_key}" deleted successfully!')
            else:
                messages.error(request, "Rule not found!")
        except Rule.DoesNotExist:
            messages.error(request, "No work rules found!")
        except Exception as e:
            messages.error(request, f"Error deleting rule: {str(e)}")
    
    return redirect('create_work_rule')

def work_report(request):
    camera = request.GET.get('camera', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page_size = int(request.GET.get('page_size', 20))
    page_number = request.GET.get('page', 1)
    
    # Build queryset
    queryset = EmailSend.objects.filter(rule_category="Work Rule").order_by('-created_at')
    
    if camera:
        queryset = queryset.filter(place=camera)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)
    
    # Pagination
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)
    
    # Get unique cameras for filter dropdown
    cameras = EmailSend.objects.filter(rule_category="Work Rule").values_list('place', flat=True).distinct()
    
    context = {
        'page_obj': page_obj,
        'cameras': cameras,
        'selected_camera': camera,
        'date_from': date_from,
        'date_to': date_to,
        'current_page_size': page_size,
        'total_count': paginator.count,
        'MEDIA_URL': settings.MEDIA_URL,
        'report_type': 'work',
    }
    return render(request, 'webapp/work_report.html', context)


def export_work_pdf(request):
    from django.template.loader import get_template
    
    records = EmailSend.objects.filter(rule_category="Work Rule").order_by("-created_at")

    place = request.GET.get("place")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if place:
        records = records.filter(place__icontains=place)
    if date_from:
        records = records.filter(created_at__date__gte=date_from)
    if date_to:
        records = records.filter(created_at__date__lte=date_to)

    # Convert images to base64 (resize to max 100px width - slightly larger)
    for r in records:
        r.image_base64 = ''
        if r.image_path:
            try:
                # Build path – same logic as no_employee
                if platform.system() == "Windows":
                    img_path = Path(settings.BASE_DIR) / r.image_path
                else:
                    img_path = Path(settings.MEDIA_ROOT) / r.image_path

                if not img_path.exists():
                    alt = Path(settings.BASE_DIR) / "recognized_cctv" / r.image_path
                    if alt.exists():
                        img_path = alt

                if img_path.exists():
                    with Image.open(img_path) as img:
                        if img.mode in ('RGBA', 'LA', 'P'):
                            img = img.convert('RGB')
                        # Resize to max 100px width (was 60px)
                        if img.width > 100:
                            ratio = 100 / img.width
                            new_size = (100, int(img.height * ratio))
                            img = img.resize(new_size, Image.Resampling.LANCZOS)
                        buffer = io.BytesIO()
                        img.save(buffer, format='JPEG', quality=75, optimize=True)
                        r.image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            except Exception:
                pass  

    template = get_template("webapp/work_pdf.html")
    html = template.render({"records": records, "request": request})

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="work_detection.pdf"'
    pisa.CreatePDF(html, dest=response, link_callback=link_callback)
    return response
