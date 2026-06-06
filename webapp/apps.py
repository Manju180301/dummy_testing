import platform

from django.apps import AppConfig
import os
import threading
import time
import warnings
import psutil
warnings.filterwarnings("ignore", category=FutureWarning)


class WebappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'webapp'

    def ready(self):

        import os
        if os.environ.get("RUN_MAIN") != "true":
            return
        
        if platform.system() == "Windows":
            from multiprocessing import current_process

            if current_process().name != "MainProcess":
                return

        from webapp.camera.camera_reader import CameraReader
        from webapp.ai.yolo_worker import ai_worker
        from webapp.ai.mp_queue import MP_FRAME_QUEUE
        from webapp.core.bridge import bridge_frames
        import threading
        from multiprocessing import Process

        # 🔹 Start AI Processes
        for i in range(2):
            p = Process(target=ai_worker, args=(i, MP_FRAME_QUEUE))
            p.daemon = True
            p.start()

        # 🔹 Start bridge thread
        threading.Thread(target=bridge_frames, daemon=True).start()
        from webapp import views
        import atexit
        from webapp.rule_executor import (
            execute_meeting_rules,
            execute_allowed_place_rules,
            execute_restricted_zone_rules,
            execute_inout_time_rules,
            execute_unknown_alert_rule,
            execute_phone_usage_rules,
            execute_helmet_rules,
            execute_no_employee_rules,
            execute_group_rules,
            execute_work_rules,
        )

        CAMERA_URLS = {
            # "Entry door": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/101",
            #"Lunch Hall": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/201",
            #"Cabin_1": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/301",
            # "Working Hall 1": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/401",
            # "Working Hall 2": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/501",
            # "Admin cabin": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/601",
            # "Conference Hall": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/701",
            #"Washroom": "rtsp://admin:Texa@321@192.168.1.2:554/Streaming/Channels/801",

        }
        # views.streams = {
        #     name:  CameraReader(name, url).start()
        #     for name, url in CAMERA_URLS.items()
        # }
        
        views.streams = {}
        for name, url in CAMERA_URLS.items():
            reader = CameraReader(name, url)
            reader.start()
            views.streams[name] = reader
    
        # ================= RULE EXECUTOR =================
        def rule_worker():
            while True:
                try:
                    
                    execute_meeting_rules()
                    execute_allowed_place_rules()
                    execute_restricted_zone_rules()
                    execute_inout_time_rules()
                    execute_unknown_alert_rule()
                    execute_phone_usage_rules()
                    execute_helmet_rules()
                    execute_no_employee_rules()
                    execute_group_rules()
                    execute_work_rules()
                    
                except Exception as e:
                    print("❌ Rule executor error:", e)
                time.sleep(5)  
                
        threading.Thread(
            target=rule_worker,
            daemon=True
        ).start()
        
        # monitor_thread = threading.Thread(target=monitor_system, daemon=True)
        # monitor_thread.start()
        #atexit.register(lambda: [c.stop() for c in views.streams.values()])
        atexit.register(
            lambda: [
                c.stop()
                for c in views.streams.values()
                if c is not None and hasattr(c, "stop")
            ]
        )


def monitor_system():
    process = psutil.Process(os.getpid())
    while True:
        cpu = process.cpu_percent(interval=1)
        ram = process.memory_info().rss / (1024 * 1024)
        print(f"📊 CPU: {cpu:.1f}% | RAM: {ram:.2f} MB")
        time.sleep(5)