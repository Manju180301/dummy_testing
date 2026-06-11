import insightface
import numpy as np
import cv2
from pathlib import Path

# ---------- Global FaceAnalysis app ----------
app = None

def get_app():
    global app
    if app is None:
        app = insightface.app.FaceAnalysis(name="buffalo_l")
        # ctx_id = 0 → use GPU 0; use -1 if you want CPU
        app.prepare(ctx_id=0, det_size=(640, 640))
    return app

app = get_app()

# ---------- Config ----------
GALLERY_DIR = Path("faces_gallery")
GALLERY_FILE = Path("output_emp.npz")

# ---------- Helper: L2 normalize ----------
def l2_norm(v: np.ndarray) -> np.ndarray:
    v = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


# ---------- Compute Embedding for One Person Directory ----------
def compute_dir_embedding(
    person_dir: Path,
    ext_tuple=(".jpg", ".jpeg", ".png", ".webp")) -> np.ndarray | None:
    embeddings = []
    used_images = []

    for ext in ext_tuple:
        for img_path in person_dir.glob(f"*{ext}"):
            img = cv2.imread(str(img_path))
            if img is None:
                continue

            faces = app.get(img)
            if not faces:
                continue

            # Use normed_embedding if available
            emb = np.array(faces[0].normed_embedding, dtype=np.float32)
            embeddings.append(emb)
            used_images.append(
                img_path.name
            )

    if not embeddings:
        print(f"❌ No valid images found in {person_dir.name}")
        return None

    mean_emb = np.mean(embeddings, axis=0)
    final_emb = l2_norm(mean_emb)

    print("\n" + "="*50)
    print(f"Employee : {person_dir.name}")
    print(f"Images Used : {len(used_images)}")

    for img in used_images:

        print(f"   ✓ {img}")

    print("="*50)

    return final_emb

# ---------- Build & Save Gallery (faces_gallery -> gallery_embeddings.npz) ----------
def build_and_save_gallery():
    gallery_embeddings = {}

    if not GALLERY_DIR.exists():
        print(f"⚠️ Gallery directory does not exist: {GALLERY_DIR}")
        return

    for person_dir in GALLERY_DIR.iterdir():
        if not person_dir.is_dir():
            continue

        person_name = person_dir.name
        print(f"🔍 Processing: {person_name}")

        emb = compute_dir_embedding(person_dir)
        if emb is not None:
            gallery_embeddings[person_name] = emb
            print(f"✅ Loaded {person_name}")
            #emb_mean = float(np.mean(emb))
            #print(f"{person_name}: {emb_mean:.3f}")
        else:
            print(f"⚠️ No valid faces for {person_name}, skipping.")

    if gallery_embeddings:
        GALLERY_FILE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(str(GALLERY_FILE), **gallery_embeddings)
        print(f"💾 Saved {len(gallery_embeddings)} entries to {GALLERY_FILE}")
    else:
        print("❌ Nothing to save (no embeddings found).")


# ---------- Optional: Load Gallery  ----------
def load_gallery():
    if not GALLERY_FILE.exists():
        raise FileNotFoundError(
            f"{GALLERY_FILE} does not exist. Run build_and_save_gallery() first."
        )
    data = np.load(str(GALLERY_FILE), allow_pickle=True)
    return {key: np.array(data[key], dtype=np.float32) for key in data.files}

def run_training(
        selected_ids=None
):

    gallery_embeddings = {}

    if not GALLERY_DIR.exists():
        return False

    for person_dir in GALLERY_DIR.iterdir():

        if not person_dir.is_dir():
            continue

        person_name = person_dir.name

        if selected_ids:

            if person_name not in selected_ids:
                continue

        emb = compute_dir_embedding(
            person_dir
        )

        if emb is not None:

            gallery_embeddings[
                person_name
            ] = emb
            
            print(f"✅ {person_name} Updated To output_emp.npz")

    if GALLERY_FILE.exists():

        old_data = np.load(
            str(GALLERY_FILE),
            allow_pickle=True
        )

        final_data = {

            key: old_data[key]

            for key in old_data.files
        }

    else:

        final_data = {}

    final_data.update(
        gallery_embeddings
    )

    np.savez(
        str(GALLERY_FILE),
        **final_data
    )
    
    print("\n")
    print("="*60)
    print(f"💾 Saved {len(final_data)} Employees")
    
    for emp in final_data.keys():
        print(f"   → {emp}")
    print(f"\nFile : {GALLERY_FILE}")
    print("="*60)

    return True


# ---------- Run once to build gallery ----------
if __name__ == "__main__":
    build_and_save_gallery()
