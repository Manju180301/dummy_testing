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
from .models import Employee,RecognizedFace,Rule
from django.core.paginator import Paginator
from .models import EmailSend
import csv
from training_app.models import FaceRecording
from django.http import JsonResponse


def _build_attendance_for_date(selected_date):
    start_dt = datetime.combine(selected_date, datetime.min.time())
    end_dt = datetime.combine(selected_date, datetime.max.time())

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

    attendance = []

    for emp_id, recs in emp_map.items():

        entry_records = [
            r for r in recs
            if r.camera_name in views.ENTRY_CAMERAS
        ]

        if not entry_records:
            continue

        first = entry_records[0]

        exit_records = [
            r for r in recs
            if r.camera_name in views.EXIT_CAMERAS
        ]

        last = exit_records[-1] if exit_records else None

        employee = Employee.objects.filter(emp_id=emp_id).first()
        emp_name = employee.emp_name if employee else "-"

        check_out_time = None
        check_out_cam = None
        total_hours = "-"

        if last:
            check_out_time = last.capture_date_time
            check_out_cam = last.camera_name

            total_hours = str(
                last.capture_date_time - first.capture_date_time
            ).split(".")[0]

        attendance.append({
            "emp_id": emp_id,
            "emp_name": emp_name,
            "image": first.image_path,
            "check_in_time": first.capture_date_time,
            "check_in_cam": first.camera_name,
            "check_out_time": check_out_time,
            "check_out_cam": check_out_cam,
            "total_hours": total_hours,
        })

    present_emp_ids = list({row["emp_id"] for row in attendance})

    return attendance, present_emp_ids


def _build_attendance_summary(start_date, end_date):

    records = (
        RecognizedFace.objects
        .filter(
            capture_date_time__date__range=(
                start_date,
                end_date
            ),
            emp_id__isnull=False
        )
        .exclude(
            emp_id__in=["", "UNKNOWN", "NO_FACE"]
        )
        .order_by("emp_id")
    )

    emp_map = {}

    for r in records:
        emp_map.setdefault(
            r.emp_id,
            []
        ).append(r)

    total_days = (
        end_date - start_date
    ).days + 1

    summary = []

    employees = Employee.objects.all().order_by("emp_id")

    for emp in employees:

        emp_records = emp_map.get(
            emp.emp_id,
            []
        )

        present_dates = set(
            r.capture_date_time.date()
            for r in emp_records
        )

        present_days = len(
            present_dates
        )

        absent_days = (
            total_days -
            present_days
        )

        image = None

        if emp_records:
            image = emp_records[0].image_path

        summary.append({
            "image": image,
            "emp_id": emp.emp_id,
            "emp_name": emp.emp_name,
            "present_days": present_days,
            "absent_days": absent_days,
        })

    return summary


def index(request):
    COMPANY_ID = "1060"

    # ================= BASIC COUNTS =================
    employees = Employee.objects.filter(company_id=COMPANY_ID)

    total_employees = employees.count()
    total_cameras = len(views.streams)

    # ================= TODAY PRESENT =================
    today = date.today()
    _, present_emp_ids = _build_attendance_for_date(today)
    today_present = len(present_emp_ids)

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
    

def get_employee_details(request):

    emp_id = request.GET.get(
        "emp_id",
        ""
    ).strip().upper()

    record = FaceRecording.objects.filter(
        emp_id=emp_id
    ).first()

    if not record:

        return JsonResponse({
            "success": False
        })

    return JsonResponse({

        "success": True,

        "employee_name":
            record.employee_name,

        "department":
            record.department

    })

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
    today = date.today()

    start_date_str = request.GET.get(
        "start_date",
        today.strftime("%Y-%m-%d")
    )

    end_date_str = request.GET.get(
        "end_date",
        today.strftime("%Y-%m-%d")
    )

    start_date = datetime.strptime(
        start_date_str,
        "%Y-%m-%d"
    ).date()

    end_date = datetime.strptime(
        end_date_str,
        "%Y-%m-%d"
    ).date()

    is_range_report = start_date != end_date
    
    start_dt = datetime.combine(
        start_date,
        datetime.min.time()
    )

    end_dt = datetime.combine(
        end_date,
        datetime.max.time()
    )

    if is_range_report:

        attendance_summary = _build_attendance_summary(
            start_date,
            end_date
        )

        attendance = []
        present_emp_ids = []

    else:

        attendance, present_emp_ids = (
            _build_attendance_for_date(
                start_date
            )
        )

        attendance_summary = []

    present_count = len(present_emp_ids)

    # Employees who are absent today
    absent_employees = Employee.objects.exclude(
        emp_id__in=present_emp_ids
    ).order_by("emp_id")

    absent_count = absent_employees.count()

    return render(request, "webapp/attendance.html", {
        "attendance": attendance,
        "is_range_report": is_range_report,
        "attendance_summary": attendance_summary,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "MEDIA_URL": settings.MEDIA_URL,
        "OS_TYPE": platform.system(),
        "present_count": present_count,
        "absent_count": absent_count,
        "absent_employees": absent_employees,
    })
    
def attendance_csv(request):

    today = date.today()

    start_date_str = request.GET.get(
        "start_date",
        today.strftime("%Y-%m-%d")
    )

    end_date_str = request.GET.get(
        "end_date",
        today.strftime("%Y-%m-%d")
    )

    start_date = datetime.strptime(
        start_date_str,
        "%Y-%m-%d"
    ).date()

    end_date = datetime.strptime(
        end_date_str,
        "%Y-%m-%d"
    ).date()

    is_range_report = start_date != end_date

    response = HttpResponse(content_type="text/csv")

    response["Content-Disposition"] = (
        f'attachment; filename="attendance_{start_date}_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # =====================================
    # DATE RANGE REPORT
    # =====================================
    if is_range_report:

        summary = _build_attendance_summary(
            start_date,
            end_date
        )

        writer.writerow([
            "Emp ID",
            "Emp Name",
            "Present Days",
            "Absent Days"
        ])
        
        for row in summary:

            writer.writerow([
                row["emp_id"],
                row["emp_name"],
                row["present_days"],
                row["absent_days"]
            ])

        return response

    # =====================================
    # SINGLE DAY REPORT
    # =====================================

    start_dt = datetime.combine(
        start_date,
        datetime.min.time()
    )

    end_dt = datetime.combine(
        end_date,
        datetime.max.time()
    )

    records = (
        RecognizedFace.objects
        .filter(
            capture_date_time__range=(
                start_dt,
                end_dt
            ),
            emp_id__isnull=False
        )
        .exclude(
            emp_id__in=[
                "",
                "UNKNOWN",
                "NO_FACE"
            ]
        )
        .order_by(
            "emp_id",
            "capture_date_time"
        )
    )

    emp_map = {}

    for r in records:
        emp_map.setdefault(
            r.emp_id,
            []
        ).append(r)

    writer.writerow([
        "Emp ID",
        "Emp Name",
        "Check In",
        "Check Out",
        "Total Hours"
    ])

    for emp_id, recs in emp_map.items():

        entry_records = [
            r for r in recs
            if r.camera_name in views.ENTRY_CAMERAS
        ]

        if not entry_records:
            continue

        first = entry_records[0]

        exit_records = [
            r for r in recs
            if r.camera_name in views.EXIT_CAMERAS
        ]

        last = exit_records[-1] if exit_records else None

        employee = Employee.objects.filter(
            emp_id=emp_id
        ).first()

        emp_name = (
            employee.emp_name
            if employee else "-"
        )

        check_in = (
            f"{first.capture_date_time.strftime('%H:%M:%S')} - "
            f"{first.camera_name}"
        )

        check_out = ""
        total_hours = ""

        if last:

            check_out = (
                f"{last.capture_date_time.strftime('%H:%M:%S')} - "
                f"{last.camera_name}"
            )

            total_hours = str(
                last.capture_date_time -
                first.capture_date_time
            ).split(".")[0]

        writer.writerow([
            emp_id,
            emp_name,
            check_in,
            check_out,
            total_hours
        ])

    writer.writerow([])

    writer.writerow(["ABSENT EMPLOYEES"])
    writer.writerow(["Emp ID", "Emp Name"])

    present_emp_ids = list(emp_map.keys())

    absent_employees = Employee.objects.exclude(
        emp_id__in=present_emp_ids
    ).order_by("emp_id")

    for emp in absent_employees:

        writer.writerow([
            emp.emp_id,
            emp.emp_name
        ])

    return response


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

#-----------------GROUP GATHERING-------------------
def create_group_gathering_rule(request):
    rule_obj,_=Rule.objects.get_or_create(
        rule_type="group_gathering",
        defaults={"rules_json":{}}
    )

    rules=rule_obj.rules_json or {}

    if request.method=="POST":
        rule_no=f"rule_{len(rules)+1}"

        rules[rule_no]={
            "place":request.POST.getlist("place"),
            "max_count":int(request.POST.get("max_count")),
            "head_email":request.POST.get("head_email"),
            "active":request.POST.get("active")=="true"
        }

        rule_obj.rules_json=rules
        rule_obj.save()
        return redirect("create_group_gathering_rule")

    
    cameras=list(streams.keys())

    return render(request,"webapp/create_group_gathering_rule.html",{
        "rules":rules,
        "cameras":cameras
    })


def toggle_group_rule(request,rule_key):
    r=Rule.objects.get(rule_type="group_gathering")
    rules=r.rules_json
    rules[rule_key]["active"]=not rules[rule_key]["active"]
    r.rules_json=rules
    r.save()
    return redirect("create_group_gathering_rule")


def delete_group_rule(request,rule_key):
    r=Rule.objects.get(rule_type="group_gathering")
    rules=r.rules_json
    del rules[rule_key]
    r.rules_json=rules
    r.save()
    return redirect("create_group_gathering_rule")


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
    response['Content-Disposition'] = 'attachment; filename="violations.pdf"'

    pisa.CreatePDF(html, dest=response)

    return response
