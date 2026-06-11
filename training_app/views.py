import os

from datetime import datetime
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import FaceRecording
from .video_processor import process_video
from .train_gallery import run_training
import numpy as np
import shutil


def enter_emp_id(request):
    return render(
        request,
        'training_app/enter_emp_id.html'
    )


def face_record(request):

    if request.method != "POST":
       return redirect("enter_emp_id")

    emp_id = request.POST.get("emp_id")
    employee_name = request.POST.get("employee_name")
    department = request.POST.get("department")
    

    if not emp_id:
        return JsonResponse(
            {"error": "Employee ID required"},
            status=400
        )

    emp_id = emp_id.strip().upper()
    
    if FaceRecording.objects.filter(
        emp_id=emp_id
    ).exists():

        return render(
            request,
            "training_app/enter_emp_id.html",
            {
                "error":
                f"{emp_id} Face Already Registered"
            }
        )

    return render(
        request,
        "training_app/face_record.html",
        {
            "emp_id": emp_id,
            "employee_name": employee_name,
            "department": department,
        }
    )

def upload_face_video(request):

    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Invalid request"},
            status=400
        )

    emp_id = request.POST.get("employee_id")
    employee_name = request.POST.get("employee_name")
    department = request.POST.get("department")
    file = request.FILES.get("video")

    if not emp_id:
        return JsonResponse(
            {"success": False, "error": "Employee ID missing"},
            status=400
        )

    if not file:
        return JsonResponse(
            {"success": False, "error": "Video file missing"},
            status=400
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{emp_id}_{timestamp}.webm"

    upload_dir = settings.FACE_VIDEO_DIR

    os.makedirs(
        upload_dir,
        exist_ok=True
    )

    filepath = os.path.join(
        upload_dir,
        filename
    )

    with open(filepath, "wb+") as dest:
        for chunk in file.chunks():
            dest.write(chunk)

    FaceRecording.objects.create(
        emp_id=emp_id,
        employee_name=employee_name,
        department=department,
        video_filename=filename,
        video_path=filepath
    )
    process_video(
        filepath,
        emp_id,
        target_images=15
    )

    return JsonResponse({
        "success": True
    })
    
def training_dashboard(request):

    gallery_path = "faces_gallery"

    employees = []

    if os.path.exists(gallery_path):

        for emp_id in sorted(os.listdir(gallery_path)):

            emp_folder = os.path.join(
                gallery_path,
                emp_id
            )

            if not os.path.isdir(emp_folder):
                continue

            files = os.listdir(emp_folder)

            #print("FILES =", files)

            image_count = len([
                f for f in files
                if f.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                )
            ])

            #print(emp_id, image_count)
            
            trained_ids = []

            output_file = "output_emp.npz"

            if os.path.exists(output_file):

                data = np.load(
                    output_file,
                    allow_pickle=True
                )

                trained_ids = list(
                    data.files
                )
                
            record = FaceRecording.objects.filter(
                emp_id=emp_id
            ).first()

            employee_name = ""

            if record:

                employee_name = record.employee_name

            employees.append({
                "emp_id": emp_id,
                "employee_name": employee_name,
                "image_count": image_count,
                "status":
                    "Trained"
                    if emp_id in trained_ids
                    else "New"
            })

    return render(

        request,

        "training_app/training_dashboard.html",
        {

            "employees": employees

        }

    )
    
def start_training(request):

    run_training()

    gallery_path = "faces_gallery"

    employees = []

    if os.path.exists(gallery_path):

        employees = sorted(
            [
                folder
                for folder in os.listdir(gallery_path)

                if os.path.isdir(
                    os.path.join(
                        gallery_path,
                        folder
                    )
                )
            ]
        )

    return render(
        request,
        "training_app/training_dashboard.html",
        {
            "employees": employees,
            "success":
            "Training Completed Successfully"
        }
    )
    
def upload_images(request):

    if request.method != "POST":

        return redirect(
            "training_dashboard"
        )

    emp_id = request.POST.get(
        "emp_id"
    )

    files = request.FILES.getlist(
        "images"
    )
    
    # print("EMP ID =", emp_id)
    # print("TOTAL FILES =", len(files))
    # print(request.FILES)

    if not emp_id:

        messages.error(
            request,
            "Employee ID Missing"
        )

        return redirect(
            "training_dashboard"
        )

    emp_folder = os.path.join(

        "faces_gallery",

        emp_id.upper()

    )

    os.makedirs(
        emp_folder,
        exist_ok=True
    )

    for file in files:
        print("Saving:", file.name)

        save_path = os.path.join(

            emp_folder,

            file.name

        )

        with open(
            save_path,
            "wb+"
        ) as dest:

            for chunk in file.chunks():

                dest.write(chunk)
        

    messages.success(

        request,

        f"{len(files)} Images Uploaded Successfully"

    )

    return redirect(
        "training_dashboard"
    )
    
def retrain_employee(request, emp_id):

    run_training(
        selected_ids=[
            emp_id
        ]
    )

    messages.success(

        request,

        f"{emp_id} Updated Successfully"

    )

    return redirect(
        "training_dashboard"
    )
        
def retrain_all(request):

    run_training()

    messages.success(

        request,

        "All Employees Updated Successfully"

    )

    return redirect(
        "training_dashboard"
    )
    
def delete_employee(
        request,
        emp_id
):

    gallery_path = os.path.join(
        "faces_gallery",
        emp_id
    )

    if os.path.exists(
        gallery_path
    ):

        shutil.rmtree(
            gallery_path
        )

    npz_file = "output_emp.npz"

    if os.path.exists(
        npz_file
    ):

        old_data = np.load(
            npz_file,
            allow_pickle=True
        )

        new_data = {}

        for key in old_data.files:

            if key != emp_id:

                new_data[key] = old_data[key]

        np.savez(
            npz_file,
            **new_data
        )

    messages.success(
        request,
        f"{emp_id} Employee Deleted Successfully"
    )

    return redirect(
        "training_dashboard"
    )
    
def retrain_selected(
        request
):

    if request.method != "POST":

        return redirect(
            "training_dashboard"
        )

    selected_ids = request.POST.getlist(
        "selected_ids"
    )

    if not selected_ids:

        messages.error(
            request,
            "No Employee Selected"
        )

        return redirect(
            "training_dashboard"
        )

    run_training(
        selected_ids=selected_ids
    )

    messages.success(
        request,
        f"Selected Employees Updated: {', '.join(selected_ids)}"
    )

    return redirect(
        "training_dashboard"
    )