# Face-Anchored Gesture Challenge for Rotating-QR Classroom Attendance

CSBP441 Computer Vision, Fall 2026. Abdulwahhab Ali, Yazan Badawie.

The board shows a QR code whose token changes every 3 s. A student scans it and enters their ID. The phone then
asks for a **random hand gesture next to the face** and takes a selfie. The server accepts the check-in only if
(i) the detected gesture equals the challenge and (ii) the face matches the student's enrolled ArcFace embedding.
The instructor sees a live count and downloads an Excel report.

**Research question (H1):** does a *face-anchored ROI cascade* raise top-1 gesture accuracy by ≥ 5 pp over full-frame
inference, with ≤ 50 ms extra latency? The cascade is BlazeFace → crop 3× the face box → YOLOv8n on the
up-scaled crop. Both pipelines use the same YOLO weights.

```
baseline : selfie ──────────────────────────────► YOLOv8n ─► gesture ┐
ours     : selfie ─► BlazeFace ─► ROI = 3× face ─► YOLOv8n ─► gesture ├─► accept iff gesture == challenge
           selfie ─► SCRFD + ArcFace (MobileFaceNet) ─► cosine vs enrolled ┘                  and sim ≥ threshold
```

## Put it online for a doctor (free)

[DEPLOY.md](DEPLOY.md) walks through hosting the app on Render's free plan with a free Supabase database (no card needed).
The admin signs in, creates a doctor account on the **Accounts** page, and the doctor runs classes from any laptop.
Each doctor sees only their own courses.

## Quick start on a laptop (no training)

1. Install **Python 3.12** from https://www.python.org/downloads/ and tick *"Add python.exe to PATH"*.
2. Double-click **`start.bat`**. The first run sets everything up, which takes a few minutes. After that it starts in seconds.
   - The console prints a first admin account (`admin@localhost` and a password) and your browser opens the sign-in
     page. Keep the black console window open during class. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` before the first
     start to choose them yourself.
3. Sign in, create a course and upload its student list once: a CSV or Excel file with a name column and a
   student-ID column, like `examples/roster_example.csv`. You can add, edit and remove students later.
4. Start a class. Leave **Let new students register their face** on for the first class. Click **Show QR code** and
   project it. **Try a check-in on this computer** tests it with the laptop webcam.
5. Students scan the QR code, type their ID, show the hand sign next to their face, and take the photo.
   - A student's first check-in saves their face. Approve each one on the course page.
6. End the class and download the Excel file.

**How phones reach the laptop.** `start.bat` tries to open a free Cloudflare HTTPS link, which phones can use from
any network and which gives them a live camera preview. If the tunnel can't connect, the QR code falls back to
`http://<laptop-ip>:8000`. Phones must then be on the same Wi-Fi as the laptop, and they use their camera app
instead of a live preview. If phones can't connect, allow Python through the Windows firewall when asked, or use a
phone hotspot.

**What runs out of the box (compromises vs. the proposal):**
- Gestures come from Google's **pretrained MediaPipe Gesture Recognizer**, not a fine-tuned YOLOv8n.
- It knows thumbs-up, peace, open palm, fist and one finger: **5 of the 6 gestures**. It has no "OK" class.
- The face threshold is a placeholder (0.35) until you run the LFW calibration.
- In the live app, the face crop is shifted down half a face height, because people hold their hand at chin or
  chest level. If the crop finds no gesture, the app retries on the whole photo.
- Tested on real photos: correct gesture in 4/4 sample photos, same person matched (similarity 0.77), a different
  person rejected (−0.05). About 90 ms per check-in on a CPU.

The YOLO training and evaluation workflow below is still needed for the **report experiments** (baseline vs ROI). It
is not needed to take attendance. To use YOLO in the app after training, set `models.gesture_backend: yolo` and add
`ok` back to `gestures` in `configs/default.yaml`.

## Repository layout

```
configs/default.yaml          all settings (gestures, models, ROI, thresholds, app)
src/gesture_attendance/
  vision/roi.py               face-anchored ROI + crop/up-scale + coordinate mapping   <- the contribution
  vision/pipelines.py         FullFramePipeline (baseline) vs FaceAnchoredROIPipeline (ours)
  vision/face_detector.py     BlazeFace (MediaPipe Tasks)
  vision/face_recognizer.py   SCRFD face detector + ArcFace MobileFaceNet, run with onnxruntime
  vision/mediapipe_gesture.py pretrained MediaPipe Gesture Recognizer (default, no training)
  vision/gesture_detector.py  YOLOv8 wrapper (after training on HaGRID)
  verify.py                   accept/reject decision, builders from config
  datasets.py, evaluation.py  test-set loading, metrics (bootstrap CI, McNemar, mAP, FAR/FRR, EER)
  app/                        FastAPI web app (accounts, courses, rotating QR, challenges, enrollment, Excel)
  app/db.py, app/store.py     SQLite or Postgres (Supabase) storage
  app/tunnel.py               optional free HTTPS link for phones (Cloudflare quick tunnel)
start.bat                     one-click setup + start on Windows (uses requirements-app.txt, no torch)
Dockerfile, DEPLOY.md         free hosting on Render + Supabase (Cloud Run and Hugging Face also work)
scripts/
  prepare_hagrid.py           6-class HaGRID subset, split by subject → YOLO format
  train_yolo.py               fine-tune YOLOv8n (same weights for both pipelines)
  predict.py                  run all pipeline configs on a test set, cache predictions
  evaluate.py                 gesture metrics, per-condition results, paired comparison vs baseline
  eval_face.py                ArcFace threshold on LFW; genuine/impostor on volunteers
  eval_e2e.py                 end-to-end FRR and FAR per attack type
  bench_latency.py            median / p95 latency, model sizes
  make_figures.py             report figures + qualitative success/failure grids
  run_app.py                  start the attendance server
notebooks/colab_pipeline.ipynb  the whole offline pipeline on a free Colab T4
tests/                        unit/integration tests (no models needed)
```

## Setup

Python 3.10–3.12 is recommended. MediaPipe and torch wheels can lag behind the newest Python.

```powershell
# Windows PowerShell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
pytest -q                        # ~15 s, no models or data needed
```

On Colab, open `notebooks/colab_pipeline.ipynb`.

The pretrained face models download on first use into `~/.cache/gesture_attendance/` (override with `GA_CACHE_DIR`):
BlazeFace short-range (0.2 MB) and InsightFace `buffalo_s` (SCRFD-500MF 2.4 MB + ArcFace MobileFaceNet 13 MB).
We run InsightFace's ONNX files directly with onnxruntime. This avoids the `insightface` pip package, which needs
a C++ compiler on Windows.

## Workflow (matches the proposal timeline)

### Weeks 7–8: data and baseline training

1. Download HaGRID annotations and images for `like, peace, palm, fist, ok, one`. Links are in the
   [HaGRID GitHub README](https://github.com/hukenovs/hagrid); the 512 px version is enough to start with. Then run:
   ```bash
   python scripts/prepare_hagrid.py --ann-dir <annotations> --images-root <images> --out data/hagrid_yolo --per-class 400 --seed 441
   ```
   The split is **by `user_id`**, so no subject is in more than one split. The subjects per split are saved in `split_users.json`.
   Keep the original resolution (`--max-side 0`, the default), because the ROI's benefit comes from the extra pixels.
2. Train on Colab:
   ```bash
   python scripts/train_yolo.py --data data/hagrid_yolo --epochs 30 --device 0
   ```
   This writes `models/gesture_yolov8n.pt` and `runs/train/gesture_yolov8n/test_metrics.json` (full-frame mAP).

### Weeks 9–10: app and volunteer test set

- Start the app (see *Running in class*) and sign in.
- Collect the volunteer set at `/collect` (laptop only; hidden on the hosted server). A consent checkbox is required. The page saves images to
  `data/classroom/images/` and writes labels to `labels.csv`. The protocol is in `data/README.md`.

### Week 11: baseline vs ROI on HaGRID test

```bash
python scripts/predict.py  --dataset hagrid --root data/hagrid_yolo --out runs/preds/hagrid
python scripts/evaluate.py --preds runs/preds/hagrid --out runs/eval/hagrid
```

### Week 12: ablations, latency and attacks on the classroom set

```bash
# default configs: full, roi_s2_up, roi_s3_up, roi_s4_up, roi_s3_noup   (add roi_s3_up_scrfd, see note below)
python scripts/predict.py  --dataset classroom --root data/classroom --out runs/preds/classroom \
       --configs full roi_s2_up roi_s3_up roi_s4_up roi_s3_noup roi_s3_up_scrfd
python scripts/evaluate.py --preds runs/preds/classroom --out runs/eval/classroom

python scripts/eval_face.py --lfw-root data/lfw --lfw-pairs data/lfw/pairsDevTrain.txt \
       --lfw-test-pairs data/lfw/pairsDevTest.txt --classroom-emb runs/preds/classroom/embeddings.npz --out runs/face
#   -> put the printed threshold into configs/default.yaml (verification.face_threshold)
python scripts/eval_e2e.py --preds runs/preds/classroom --threshold runs/face/threshold.json

python scripts/bench_latency.py --images-dir data/classroom/images --device cpu   # laptop
python scripts/bench_latency.py --images-dir data/classroom/images --device 0     # Colab T4
```

`predict.py` uses the gesture backend from the config (MediaPipe by default). Pass `--weights models/gesture_yolov8n.pt`
to evaluate the YOLO model from the proposal. You can run both and report them as two gesture models.
`roi_y_shift` from the config applies too: set `--set pipeline.roi_y_shift=0` for the proposal's centred ROI.

Config names: `full`, or `roi_s<scale>_<up|noup>[_scrfd]`. The `noup` variant pastes the crop at native resolution
instead of letting YOLO enlarge it. That is ablation (c).

What you get:
- `runs/eval/*/report.md`: top-1 accuracy with 95% bootstrap CI, accuracy per condition, mAP@0.5 (HaGRID),
  wrong-gesture FAR, background-hand FAR, face-found and fallback rates, and a **paired** comparison against `full`
  (accuracy delta with bootstrap CI, exact McNemar p-value, and whether the ≥ 5 pp H1 target is met), overall and
  per condition.
- `runs/eval/classroom/e2e.md`: FRR for genuine students, and FAR for impostor faces, wrong gestures, background hands
  and replayed photos.
- `runs/latency/*.csv`: median, p95, per-stage time, and the extra latency of ROI over full; plus `model_sizes.csv`.

### Week 13: figures and failure analysis

```bash
python scripts/make_figures.py --preds runs/preds/classroom --eval runs/eval/classroom --images-root data/classroom \
       --latency runs/latency/latency_cpu.csv runs/latency/latency_0.csv --out runs/figures/classroom
```

The `qualitative_roi_fixes_*`, `qualitative_roi_breaks_*` and `qualitative_both_wrong_*` grids draw the face box,
the ROI and the detections. Use them for the "where ROI does not help" discussion.

## Running in class

```bash
python scripts/run_app.py --port 8000 --preload --tunnel --open     # what start.bat runs
```

The console prints the sign-in URL. Accounts live in the database: the first admin comes from `ADMIN_EMAIL` /
`ADMIN_PASSWORD`, or is generated and printed on first start. Admins add doctor accounts on `/admin`.

1. Course page: upload the student list once per course (CSV/Excel with a name and a student-ID column; see
   `examples/roster_example.csv`), then add, edit or remove students as the semester goes on.
2. Start a class, with **Let new students register their face** on for the first lecture.
3. **Show QR code** opens the board. The QR code rotates every 3 s and encodes `/q/<class id>/<token>`.
4. Students scan the code, enter their ID, show the hand sign, and take the photo.
5. First check-in = enrollment: the face embedding is stored as *pending* and you approve it on the course page.
   An enrollment whose face matches another student in the course is flagged ("Face looks like another student's").
6. **Download this class** lists name, ID, Present / Not present, time, method and flags, with Summary and Flags
   sheets. **Download all classes** gives the course matrix. Removed students stay in classes they attended.

Storage is SQLite (`data/app/attendance.db`) on a laptop, or Postgres when `DATABASE_URL` is set.
`python scripts/run_app.py --hosted` is the server mode used on Render and other hosts (see DEPLOY.md).

**Phones and HTTPS.** A live camera preview needs HTTPS. On plain `http://<laptop-ip>:8000` the page falls back to
the phone's camera picker, which still works. The easiest way to get HTTPS is a free Cloudflare quick tunnel:

```bash
cloudflared tunnel --url http://localhost:8000          # prints https://<random>.trycloudflare.com
python scripts/run_app.py --set app.base_url=https://<random>.trycloudflare.com --preload
```

If phones connect over the campus Wi-Fi instead, allow Python through the Windows firewall and make sure the network
lets devices reach each other.

Switch the pipeline for a live A/B demo with `--set pipeline.mode=full`.

## Anti-abuse measures and their limits (useful for the report)

| Threat | Measure | Remaining risk |
|---|---|---|
| QR photo forwarded to absent friend | token valid for the current and previous 3 s window only; after the scan a 120 s ticket is bound to the phone | the link can be relayed live within ~6 s |
| Friend checks in for you | face must match the enrolled embedding; `face_mismatch` flagged | look-alike above threshold (measure FAR) |
| Old photo of you uploaded | random gesture; one selfie per challenge; challenge expires in 60 s; EXIF time older than 10 min rejected; uploads tagged `camera` / `file` | a stored photo shows *some* gesture: 1/6 chance per attempt, so **1 − (5/6)³ ≈ 42% within 3 attempts**. Lower `max_attempts`, or use a two-gesture challenge (1/36) as future work. `eval_e2e.py` reports this number. |
| One phone checks in many people | per-device cookie; `shared_device` flag | clearing cookies or using a different browser |
| Enrolling someone else's face | instructor confirms enrollments; `duplicate_face` flag | enrollment in the first lecture must be supervised |

Privacy: selfies are processed in memory and never written to disk. Only 512-d embeddings are stored, and an
instructor can delete a student's embedding with **reset**. The volunteer test set is kept locally and is not published.

## Notes and known issues

- **BlazeFace range.** MediaPipe Tasks only ships the *short-range* BlazeFace model, which is meant for faces
  within about 2 m. The full-range model does not load in the current Tasks API. Short-range finds selfie faces well
  but misses small faces in wide shots. This matters for HaGRID test images and the far/crowded condition. When no
  face is found, the ROI pipeline falls back to the full frame (`fallback_rate` in the report). The
  `roi_s3_up_scrfd` config anchors the ROI with SCRFD instead. SCRFD is already loaded for ArcFace and finds much
  smaller faces. Report both, and treat the anchor choice as an extra ablation.
- **Domain.** HaGRID training images are mostly frontal, at a similar distance to the camera. ROI crops show hands
  larger than in training. Ultralytics' default scale augmentation covers part of this gap. If ROI breaks cases that
  full-frame gets right, check the qualitative grids for that.
- `mAP@0.5` in `evaluate.py` is computed at the deployed confidence threshold (0.25), so it is a little lower than
  Ultralytics' `val` mAP, which uses conf 0.001. Use `train_yolo.py`'s `test_metrics.json` for the standard full-frame number.
- For latency, ArcFace is timed separately because both pipelines need it. H1's ≤ 50 ms budget refers to
  `extra_vs_full_median_ms` in the latency CSV.

## Licenses

YOLOv8 / Ultralytics: AGPL-3.0. HaGRID: CC BY-SA 4.0. InsightFace pretrained models: non-commercial research use.
MediaPipe: Apache-2.0. LFW: research use.
