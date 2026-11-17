# 🧩 XPano Docker

![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)
![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED)
![Xpano](https://img.shields.io/badge/stitching-Xpano-6ee7f2)
![OpenCV](https://img.shields.io/badge/OpenCV-SIFT%20%2B%20RANSAC-5C3EE8)

**A self-hosted review tool for panorama sequences, built around the
[Xpano](https://github.com/krupkat/xpano) stitching engine.**

It scans a mounted photo library, finds candidate panorama sweeps, shows them in
a browser interface, stitches a chosen group, and replaces the source photos
with the resulting panorama only after an explicit confirmation. The originals
and their sidecars stay in a recoverable trash directory with an undo record.

No cloud, no account, no background rewriting. A scan never changes files;
replacement is a separate, confirmed action.

## ✨ What it does

- 🗂️ **Folder-scoped indexing** — add only the library folders you want to test;
  each folder keeps its own photos, groups, and scan status.
- 🔍 **Candidate detection** — capture time, camera/lens metadata, SIFT feature
  matching, RANSAC homography, and cumulative drift separate real sweeps from
  bursts.
- 🖥️ **Web review** — group cards with cover thumbnails, member metadata,
  confidence, status, and a real-size popup for every photo and the panorama.
- 🧵 **Xpano stitching** — runs headlessly, writes the result to the data volume,
  and serves a full-resolution preview before anything is replaced.
- ♻️ **Safe replacement** — writes the panorama first, moves originals and
  `.xmp`, `.json`, `.yml`, `.yaml`, `.aae`, `.dop` sidecars to trash, then
  publishes the panorama. A completed replacement can be undone.
- 📌 **Persistent jobs** — scans, stitches, replacements, and undos live in
  SQLite; the interface reconnects to an active job after a reload.
- 🧾 **Audit trail** — every replacement records source paths, trash paths, the
  published panorama, timestamps, and errors.

## ⚙️ How it works

```text
watched folder ──▶ scanner ──▶ metadata + thumbnails
                      │
                      ▼
             candidate sequences ──▶ SIFT/RANSAC pair checks ──▶ groups
                      │
                      ▼
              browser review ──▶ Xpano stitch ──▶ preview ──▶ confirmed replace
                                                                  │
                                                                  ▼
                                                  originals in trash + undo record
```

Only explicitly added folders are scanned. The library root is never indexed
implicitly. A rescan rebuilds only the selected folder's photos and candidate
groups; other folders keep their data.

## ✅ Requirements

- Docker 24 or newer with Compose v2.
- A mounted photo library. Replacement needs read/write access to the mounted
  tree; review and stitching only need read access.
- About 2 GB of RAM for the container, plus disk space for thumbnails, stitch
  results, and the trash.
- A POSIX filesystem for the data directory (ext4 or similar). The photo library
  may be a network or NTFS mount; the trash is deliberately kept outside it so
  PhotoPrism does not index it.
- JPEG, PNG, TIFF, WebP, and BMP input. RAW and HEIC are not indexed in this
  version.

The image is based on Ubuntu 24.04 and installs Xpano from the
`ppa:krupkat/code` package.

## 🚀 Quick start

```sh
git clone https://github.com/yeswolf/xpano-docker.git
cd xpano-docker
cp .env.example .env
```

Edit `.env` with the host paths and bind address:

```dotenv
PHOTO_LIBRARY=/srv/photos
DATA_DIR=./data
BIND_ADDRESS=127.0.0.1
PORT=3040
```

Then build and start the stack:

```sh
docker compose up -d --build
```

Open `http://127.0.0.1:3040` (or the address you configured in
`BIND_ADDRESS`). To reach it from the LAN, set `BIND_ADDRESS` to the host's LAN
IP address or `0.0.0.0`.

## 🔧 Configuration

### Compose variables

These are read by `docker-compose.yml` from `.env` or the environment. The
tracked `.env.example` contains placeholders; the real `.env` is gitignored.

| Variable | Default | Meaning |
|---|---|---|
| `PHOTO_LIBRARY` | `./photos` | Host path mounted at `/library`. Replacement writes here. |
| `DATA_DIR` | `./data` | Host path mounted at `/data` for SQLite, thumbnails, stitches, and trash. |
| `BIND_ADDRESS` | `127.0.0.1` | Host address for the published web port. The service has no authentication; do not bind it to the internet. |
| `PORT` | `3040` | Published host port. The container always listens on `3040`. |

### Application variables

Defaults match the Dockerfile and `pano_xpano.config.Settings.from_env`.

| Variable | Default | Meaning |
|---|---|---|
| `PANORAMA_LIBRARY_ROOT` | `/library` | Root of the photo library inside the container. |
| `PANORAMA_DATA_DIR` | `/data` | Root of persistent service data inside the container. |
| `PANORAMA_XPANO_BIN` | `Xpano` | Xpano executable; the image uses `/usr/local/bin/Xpano`. |
| `PANORAMA_HOST` | `0.0.0.0` | Bind address inside the container. |
| `PANORAMA_PORT` | `3040` | Port inside the container. |
| `PANORAMA_DETECTOR_VERSION` | `sift-v1` | Detector version stored with groups; changing it gives new group IDs. |
| `PANORAMA_OUTPUT_EXT` | `.jpg` | Extension of the stitched panorama. |
| `PANORAMA_STITCH_TIMEOUT` | `600` | Xpano timeout in seconds. |
| `PANORAMA_USE_XVFB` | `0` | Run Xpano under `xvfb-run` when it needs a display; the image sets `1`. |
| `PANORAMA_THUMB_SIZE` | `360` | Maximum thumbnail edge in pixels. |

### Detection settings

Time window, no-EXIF window, minimum SIFT inliers, minimum pair translation,
cumulative drift threshold, and maximum candidate pairs are edited on the
**Settings** page and stored in `/data/settings.json`. The defaults target
ordinary handheld sweeps:

| Setting | Default |
|---|---:|
| Time between consecutive frames | 20 s |
| No-EXIF time window | 5 s |
| Minimum RANSAC inliers | 18 |
| Minimum pair translation | 1.5% |
| Minimum cumulative drift | 8% |
| Maximum candidate pairs | 12000 |

## 🐳 Build the image manually

```sh
docker build -t pano-xpano .
```

Run it with a bind-mounted library and a data directory:

```sh
docker run -d --name pano-xpano \
  --restart unless-stopped \
  -p 127.0.0.1:3040:3040 \
  -v "/path/to/photos:/library" \
  -v "/path/to/pano-data:/data" \
  -e PANORAMA_LIBRARY_ROOT=/library \
  -e PANORAMA_DATA_DIR=/data \
  -e PANORAMA_XPANO_BIN=/usr/local/bin/Xpano \
  -e PANORAMA_USE_XVFB=1 \
  pano-xpano
```

The container runs as root because the mounted library may be written by the
container during replacement. Use a dedicated data directory and keep the
service on a trusted LAN.

Smoke test the image:

```sh
docker run --rm pano-xpano Xpano --version
docker run --rm pano-xpano /opt/venv/bin/python -c "import pano_xpano; print('ok')"
```

## 🗄️ Data layout

Inside the container:

| Path | Contents |
|---|---|
| `/data/state/pano-xpano.sqlite3` | Folders, photos, groups, stitches, jobs, operations. |
| `/data/thumbs/` | Thumbnails served to the interface. |
| `/data/stitch/` | Stitched results before replacement. |
| `/data/trash/<operation>/` | Original files and sidecars moved by a replacement. |
| `/data/settings.json` | Editable detection settings. |
| `/library` | Read-write photo library mount. |

Keep `/data` on a POSIX filesystem. The trash lives outside the library, so
PhotoPrism does not index it.

## 🧭 Workflow

1. Open the web interface and add a folder relative to the library root (for
   example `2024` or `2024/05`), or use **Browse** to pick a subdirectory.
2. Press **Scan** on the folder. A scan never changes files.
3. Review the candidate groups and their member photos.
4. Press **Make panorama**. Xpano writes the result to `/data/stitch/`, not to
   the library.
5. Inspect the preview, including the real-size popup if you need to judge
   sharpness and seams.
6. Press **Replace** and type `REPLACE` in the confirmation prompt.
7. The source photos and sidecars move to `/data/trash/<operation>/`, and the
   panorama is published next to the first source photo as
   `PANO_<timestamp>_<group id>.jpg`.
8. In PhotoPrism, run `photoprism index --cleanup` so its index drops the
   removed files and picks up the panorama.

A completed replacement can be undone from **Operations**. Undo moves the
panorama out of the library and restores every original and sidecar. Removing a
watched folder only removes its index; files, stitches, and the operation audit
stay on disk.

## 🔌 API

The service exposes JSON endpoints under `/api`:

- `/healthz`
- `/api/folders`, `/api/folders/browse`, `/api/folders/<id>/scan`, `/api/scan`
- `/api/groups`, `/api/groups/<id>`
- `/api/groups/<id>/stitch`, `/api/groups/<id>/replace`
- `/api/groups/<id>/preview`
- `/api/photos/<key>/original`
- `/api/thumbnails/<key>`
- `/api/operations`, `/api/operations/<id>/undo`
- `/api/jobs/<id>`, `/api/jobs?active=true`
- `/api/settings`

## 🔒 Security

The service has no authentication and no multi-user separation. Bind it to a
trusted LAN address and never expose it to the internet. Replacement writes to
the mounted library, so the container's view of the library must be the tree
you intend to modify.

## ⚠️ Known limitations

- RAW and HEIC files are not indexed in this version; convert them to JPEG or
  TIFF first.
- The detector compares consecutive photos in the same directory. A panorama
  split across directories or shot with long pauses must be grouped manually
  (this version has no manual merge or split).
- Xpano's automatic group detection is used indirectly: the service computes its
  own candidate groups and invokes Xpano once per approved group.
- PhotoPrism is not notified by the service; run its cleanup command after
  replacements.
- No authentication and no multi-user separation.

## 🛠️ Development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The tests use synthetic images and temporary directories. The detector test
generates an overlapping pair and checks that SIFT/RANSAC confirms it. The
replacement tests exercise trash, rollback, and undo without touching files
outside a pytest temporary directory.

## 🙏 Credits

- [Xpano](https://github.com/krupkat/xpano) — the stitching engine.
- [PhotoPrism](https://www.photoprism.app/) — the library workflow this tool is
  designed around.
- [FastAPI](https://fastapi.tiangolo.com/), [OpenCV](https://opencv.org/),
  [Pillow](https://python-pillow.org/), and
  [ExifTool](https://exiftool.org/) — the application stack.

## 📄 License

No `LICENSE` file yet — usage conditions for the project's own code are not
defined. Xpano, PhotoPrism, and the other third-party components keep their
respective licenses.
