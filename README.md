# WIPTOWN Expense Tracker

ระบบจัดการค่าใช้จ่ายรายเดือน รองรับ PostgreSQL (Railway) และ SQLite (Local)

---

## 🚀 Deploy บน Railway (สาธารณะ)

### ขั้นตอน

**1. อัปโหลดทุกไฟล์ขึ้น GitHub**
- ลบ repo เก่าใน GitHub แล้วสร้างใหม่ (กันไฟล์เก่าค้าง)
- อัปโหลดไฟล์ทั้งหมดในโฟลเดอร์นี้

**2. Deploy บน Railway**
- เปิด railway.app → New Project → Deploy from GitHub
- เลือก repo

**3. เพิ่ม PostgreSQL**
- ในหน้า canvas กด `+ New` → Database → PostgreSQL

**4. ตั้ง Variable ใน wiptown service**
- คลิก service → Variables → New Variable
- **Name:** `DATABASE_URL`
- **Value:** พิมพ์ `${{` แล้วเลือก **Postgres.DATABASE_URL** จาก autocomplete
  
  ⚠️ ห้ามพิมพ์เอง — ต้องเลือกจาก dropdown เท่านั้น

**5. รอ Deploy → Generate Domain**
- Settings → Networking → Generate Domain
- เปิด URL ได้เลย

---

## 💻 รัน Local

### Mac / Linux
```bash
bash start.sh
```

### Windows
```bash
start.bat
```

### หรือ
```bash
pip install -r requirements.txt
python app.py
```

เปิด `http://localhost:8765`

---

## 📁 โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|------|---------|
| `app.py` | Flask server + REST API (production-grade) |
| `index.html` | UI ทั้งหมด |
| `requirements.txt` | Flask, gunicorn, psycopg2 |
| `Procfile` | บอก Railway วิธีรัน (gunicorn) |
| `railway.toml` | Railway config + healthcheck |
| `.python-version` | Python 3.11 |

---

## 🏗 Architecture

- **Server:** Flask + Gunicorn (production WSGI)
- **DB Local:** SQLite (auto-created)
- **DB Production:** PostgreSQL with connection pooling
- **Healthcheck:** `/health` endpoint
- **CORS:** เปิดให้ทุก origin

---

## 🐛 Troubleshooting

**Application failed to respond:**
- ตรวจว่า `DATABASE_URL` ตั้งจาก autocomplete แล้ว
- ห้ามตั้ง `PORT` variable เอง

**Healthcheck failed:**
- ดู Deploy Logs ว่า DB connect สำเร็จไหม

**Build failed:**
- ตรวจ requirements.txt และ Python version
