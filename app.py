from flask import Flask, render_template_string, request, jsonify, send_from_directory, session, redirect, url_for
import requests
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import pytz
from PIL import Image, ImageDraw, ImageFont
import io
import textwrap

app = Flask(__name__)
app.secret_key = 'bab_al_rahma_secret_key_2026'

# ========= إعدادات =========
UPLOAD_FOLDER = 'uploads'
ADMIN_PASS = 'AAAAVSH8EHD BDOIDOHEVVSGUDIHDGHSIVXB BBXU8EIYWGBWI8DHKSHF6283883GRB8R8IEVVSBSV'
API_KEY_UPLOAD = '3fd6caa2e26d2b535c568e6616891b46'
SUDAN_TZ = pytz.timezone('Africa/Khartoum')
BROADCAST_MSG = {"text": "", "time": 0} # تخزين اخر إذاعة

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌙 باب الرحمة</title>
<link href="https://fonts.googleapis.com/css2?family=Amiri+Quran:wght@400;700&family=Cairo:wght@700;900&display=swap" rel="stylesheet">
<style>
* {margin:0; padding:0; box-sizing:border-box}
body {background: #000; color: #fff; font-family: 'Cairo', sans-serif; padding: 15px;}
.container {max-width: 900px; margin: auto}
.logo {font-size: 42px; font-weight: 900; color: #ffd700; text-align: center; margin-bottom: 20px; text-shadow: 0 0 30px #ffd700;}
.card {background: #111; border: 3px solid #333; border-radius: 15px; padding: 20px; margin-bottom: 20px;}
.card h2 {color: #ffd700; text-align: center; margin-bottom: 15px; font-size: 24px; font-weight: 900;}
.digital-clock {background: #000; border: 5px solid #00ff00; border-radius: 10px; padding: 30px; margin: 20px 0; text-align: center;}
.time-large {font-size: 80px; color: #00ff00; font-family: monospace; font-weight: 900; letter-spacing: 10px;}
.date-large {font-size: 24px; color: #ffaa00; margin-top: 10px; font-weight: 700;}
.weekdays {display: flex; justify-content: center; gap: 8px; margin-top: 15px; flex-wrap: wrap;}
.day {padding: 8px 12px; background: #222; border-radius: 8px; font-weight: 700; font-size: 16px; border: 2px solid #444;}
.day.active {background: #00ff00; color: #000; border-color: #00ff00; box-shadow: 0 0 15px #00ff00;}
.prayer-digital {background: #000; border: 4px solid #ff0000; border-radius: 8px; padding: 25px 15px; margin: 12px 0; text-align: center;}
.prayer-name {font-size: 22px; color: #ffd700; margin-bottom: 8px; font-weight: 900;}
.prayer-time {font-size: 56px; color: #ff0000; font-family: monospace; font-weight: 900; letter-spacing: 8px;}
.next-prayer {background: linear-gradient(135deg, #ff0000, #aa0000); border: 4px solid #ffd700; border-radius: 12px; padding: 20px; margin: 15px 0; text-align: center;}
.countdown {font-size: 48px; color: white; font-family: monospace; font-weight: 900;}
select, input {width: 100%; padding: 14px; border-radius: 10px; border: 3px solid #d4af37; background: #1a1a1a; color: #ffd700; font-size: 18px; margin-bottom: 10px; font-weight: 700;}
.btn {width: 100%; background: linear-gradient(135deg, #ffd700, #ffaa00); color: #000; border: none; padding: 16px; font-size: 19px; font-weight: 900; border-radius: 10px; cursor: pointer; margin: 8px 0;}
.quran-text {font-family: 'Amiri Quran', serif; font-size: 32px; line-height: 3; color: #ffd700; text-align: center; padding: 20px; background: #0a0a0a; border-radius: 10px;}
.khutba-card {background: linear-gradient(135deg, #2d1a5d, #1a0f3d); border: 3px solid #ffd700; padding: 25px; border-radius: 15px; text-align: center; margin: 20px 0;}
.zikr-img {width: 100%; border-radius: 15px; border: 3px solid #ffd700; margin-top: 15px;}
.footer {text-align: center; padding: 30px; margin-top: 40px; border-top: 3px solid #333; color: #ffd700; font-size: 20px; font-weight: 900;}
.broadcast-bar {position: fixed; top: -100px; left: 0; right: 0; background: linear-gradient(90deg, #ff0000, #aa0000); color: #fff; text-align: center; padding: 15px; font-size: 20px; font-weight: 900; z-index: 9999; transition: top 0.5s; border-bottom: 3px solid #ffd700;}
.broadcast-bar.show {top: 0;}
@media (max-width: 600px) {.time-large {font-size: 50px}.prayer-time {font-size: 38px}}
</style>
</head>
<body>

<div class="broadcast-bar" id="broadcast-bar"></div>

<div class="container">
    <div class="logo">🌙 باب الرحمة 🌙</div>

    <div class="digital-clock">
        <div class="time-large" id="current-time">00:00:00</div>
        <div class="date-large" id="hijri-date">جاري التحميل...</div>
        <div class="date-large" id="gregorian-date"></div>
        <div class="weekdays" id="weekdays"></div>
    </div>

    <div class="next-prayer" id="next-prayer-box" style="display:none">
        <h3>🕌 الصلاة القادمة: <span id="next-prayer-name">الفجر</span></h3>
        <div class="countdown" id="countdown">00:00:00</div>
    </div>

    <div class="card">
        <h2>🕌 مواقيت الصلاة</h2>
        <select id="city" onchange="loadPrayers()">
            <option value="Khartoum">الخرطوم</option>
            <option value="Omdurman">أم درمان</option>
            <option value="Makkah">مكة المكرمة</option>
        </select>
        <button class="btn" onclick="enableReminder()">🔔 تشغيل تذكير الأذان</button>
        <div id="prayers"></div>
    </div>

    <div class="card" id="zikr-card" style="display:none">
        <h2>📿 ذكر اليوم</h2>
        <img id="zikr-image" class="zikr-img" src="" alt="ذكر اليوم">
    </div>

    <div class="khutba-card" id="khutba-box" style="display:none">
        <h2 style="color:#ffd700; margin-bottom:15px">📢 خطبة الجمعة</h2>
        <div style="font-size: 22px; color: #ffd700; line-height: 2.5;" id="khutba-text"></div>
    </div>

    <div class="card">
        <h2>📖 القرآن الكريم - مشاري العفاسي</h2>
        <select id="surah">
            <option value="67">سورة الملك</option>
            <option value="18">سورة الكهف</option>
            <option value="36">سورة يس</option>
        </select>
        <button class="btn" onclick="searchQuran()">🔍 استمع</button>
        <div id="quran-result" style="margin-top:15px"></div>
    </div>

    <div class="footer">
        وقف خيري<br>
        آل محمد بابكر & آل المبارك أحمد
    </div>
</div>

<audio id="adhan-audio" src="https://server8.mp3quran.net/afs/001.mp3" preload="auto"></audio>

<script>
let prayerTimes = {};
let reminderEnabled = false;
const weekdays_ar = ['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'];

// فحص الإذاعة كل 3 ثواني
setInterval(() => {
    fetch('/api/broadcast').then(r=>r.json()).then(d=>{
        if(d.text && d.time > (window.lastBroadcast || 0)) {
            window.lastBroadcast = d.time;
            const bar = document.getElementById('broadcast-bar');
            bar.innerText = '📢 ' + d.text;
            bar.classList.add('show');
            setTimeout(()=> bar.classList.remove('show'), 8000);
        }
    });
}, 3000);

function updateClock() {
    const now = new Date();
    const sudanTime = new Date(now.toLocaleString('en-US', {timeZone: 'Africa/Khartoum'}));
    const h = String(sudanTime.getHours()).padStart(2,'0');
    const m = String(sudanTime.getMinutes()).padStart(2,'0');
    const s = String(sudanTime.getSeconds()).padStart(2,'0');
    document.getElementById('current-time').innerText = `${h}:${m}:${s}`;

    const todayIndex = (sudanTime.getDay() + 6) % 7;
    let daysHtml = '';
    weekdays_ar.forEach((day, i) => {
        daysHtml += `<div class="day ${i === todayIndex? 'active' : ''}">${day}</div>`;
    });
    document.getElementById('weekdays').innerHTML = daysHtml;

    if(todayIndex === 4) {
        document.getElementById('khutba-box').style.display = 'block';
        document.getElementById('khutba-text').innerText = 'خطبة الجمعة: تذكر أن الدنيا فانية والآخرة باقية';
    }

    fetch('/uploads/latest.txt').then(r => r.text()).then(img => {
        if(img.trim()) {
            document.getElementById('zikr-image').src = '/uploads/' + img.trim() + '?v=' + Date.now();
            document.getElementById('zikr-card').style.display = 'block';
        }
    }).catch(()=>{});

    if(prayerTimes && Object.keys(prayerTimes).length > 0) {
        updateCountdown(sudanTime);
    }
}
setInterval(updateClock, 1000);
updateClock();

async function loadPrayers() {
    const city = document.getElementById('city').value;
    const res = await fetch(`/api/prayers?city=${city}`);
    const data = await res.json();
    if(data.error) return;
    prayerTimes = data.timings;
    document.getElementById('hijri-date').innerText = data.hijri;
    document.getElementById('gregorian-date').innerText = data.gregorian;
    let html = '';
    for(let p in prayerTimes) {
        html += `<div class="prayer-digital"><div class="prayer-name">${p}</div><div class="prayer-time">${prayerTimes[p]}</div></div>`;
    }
    document.getElementById('prayers').innerHTML = html;
    updateCountdown(new Date());
}

function updateCountdown(now) {
    const sudanTime = new Date(now.toLocaleString('en-US', {timeZone: 'Africa/Khartoum'}));
    const currentSeconds = sudanTime.getHours() * 3600 + sudanTime.getMinutes() * 60 + sudanTime.getSeconds();
    const times = Object.entries(prayerTimes);
    for(let i = 0; i < times.length; i++) {
        const [name, time] = times[i];
        const [h, m] = time.split(':').map(Number);
        let prayerSeconds = h * 3600 + m * 60;
        if(prayerSeconds > currentSeconds) {
            let diff = prayerSeconds - currentSeconds;
            const hours = Math.floor(diff / 3600);
            const mins = Math.floor((diff % 3600) / 60);
            const secs = diff % 60;
            document.getElementById('next-prayer-name').innerText = name;
            document.getElementById('countdown').innerText = `${String(hours).padStart(2,'0')}:${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
            document.getElementById('next-prayer-box').style.display = 'block';
            return;
        }
    }
}

function enableReminder() {
    reminderEnabled = true;
    alert('🔔 تم تفعيل تذكير الأذان');
    setInterval(checkPrayerTime, 1000);
}

function checkPrayerTime() {
    if(!reminderEnabled ||!prayerTimes) return;
    const now = new Date();
    const sudanTime = new Date(now.toLocaleString('en-US', {timeZone: 'Africa/Khartoum'}));
    const current = sudanTime.getHours().toString().padStart(2,'0') + ':' + sudanTime.getMinutes().toString().padStart(2,'0');
    if(sudanTime.getSeconds() === 0) {
        for(let p in prayerTimes) {
            if(prayerTimes[p] === current) {
                document.getElementById('adhan-audio').play();
                alert(`🔔 حان وقت ${p}`);
            }
        }
    }
}

async function searchQuran() {
    const surah = document.getElementById('surah').value;
    const res = await fetch(`/api/quran/${surah}`);
    const data = await res.json();
    document.getElementById('quran-result').innerHTML = `
        <div class="quran-text">﴿ ${data.first_ayah} ﴾</div>
        <div style="text-align:center; color:#ffd700; margin-top:10px; font-size:20px">سورة ${data.surah_name}</div>
        <audio controls autoplay style="width:100%; margin-top:15px" src="${data.audio_url}"></audio>
    `;
}
window.onload = loadPrayers;
</script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><title>لوحة الأدمن</title>
<style>
body{background:#000;color:#ffd700;font-family:Cairo;padding:20px}
.box{background:#111;border:3px solid #ffd700;padding:20px;border-radius:15px;max-width:600px;margin:auto}
input,textarea,select{width:100%;padding:12px;margin:10px 0;background:#222;color:#ffd700;border:2px solid #ffd700;border-radius:8px;font-size:18px}
.btn{background:#ffd700;color:#000;padding:12px;border:none;border-radius:8px;font-weight:900;font-size:18px;cursor:pointer;width:100%;margin-top:10px}
h2{text-align:center}
</style></head>
<body>
<div class="box">
    <h2>🌙 لوحة تحكم باب الرحمة</h2>
    {% if not logged_in %}
    <form method="POST">
        <input type="password" name="password" placeholder="كلمة سر الأدمن">
        <button class="btn">دخول</button>
    </form>
    {% else %}
    <h3>1. رفع صورة الأذكار يدوي</h3>
    <form method="POST" enctype="multipart/form-data" action="/upload">
        <input type="hidden" name="key" value="{{api_key}}">
        <input type="file" name="file" accept="image/*" required>
        <button class="btn">رفع الصورة</button>
    </form>

    <h3>2. توليد صورة الأذكار تلقائي</h3>
    <form method="POST" action="/admin/generate">
        <select name="type">
            <option value="morning">أذكار الصباح</option>
            <option value="evening">أذكار المساء</option>
        </select>
        <button class="btn">توليد ورفع الصورة</button>
    </form>

    <h3>3. إذاعة للموقع</h3>
    <form method="POST" action="/admin/broadcast">
        <textarea name="msg" rows="3" placeholder="اكتب الرسالة هنا..."></textarea>
        <button class="btn">إرسال إذاعة</button>
    </form>

    <a href="/admin/logout"><button class="btn" style="background:#ff0000;color:#fff">خروج</button></a>
    {% endif %}
</div>
</body></html>
"""

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASS:
            session['admin'] = True
            return redirect(url_for('admin'))
        else:
            return "كلمة السر خطأ"
    return render_template_string(ADMIN_HTML, logged_in=session.get('admin'), api_key=API_KEY_UPLOAD)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin'))

@app.route('/admin/broadcast', methods=['POST'])
def broadcast():
    if not session.get('admin'): return "غير مصرح", 403
    global BROADCAST_MSG
    BROADCAST_MSG = {"text": request.form.get('msg'), "time": datetime.now().timestamp()}
    return redirect(url_for('admin'))

@app.route('/api/broadcast')
def get_broadcast():
    return jsonify(BROADCAST_MSG)

@app.route('/admin/generate', methods=['POST'])
def generate_zikr():
    if not session.get('admin'): return "غير مصرح", 403

    ztype = request.form.get('type')
    zikr_text = "أصبحنا وأصبح الملك لله" if ztype == "morning" else "أمسينا وأمسى الملك لله"

    # تصميم الصورة
    img = Image.new('RGB', (1080, 1080), color = '#0a0a0a')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 70) # لو ما لقى الخط هيستخدم الافتراضي
    except:
        font = ImageFont.load_default()

    draw.text((540, 300), "📿 ذكر اليوم", font=font, fill="#ffd700", anchor="mm")
    wrapped_text = textwrap.fill(zikr_text, width=20)
    draw.text((540, 550), wrapped_text, font=font, fill="#fff", anchor="mm", align="center")
    draw.text((540, 900), "باب الرحمة", font=font, fill="#ffd700", anchor="mm")

    filename = f"zikr_{ztype}_{datetime.now().strftime('%Y%m%d')}.jpg"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img.save(filepath)

    with open(os.path.join(app.config['UPLOAD_FOLDER'], 'latest.txt'), 'w') as f:
        f.write(filename)
    return redirect(url_for('admin'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if request.form.get('key')!= API_KEY_UPLOAD: return jsonify({'error': 'مفتاح خطأ'}), 403
    file = request.files['file']
    filename = secure_filename(f"zikr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    with open(os.path.join(app.config['UPLOAD_FOLDER'], 'latest.txt'), 'w') as f:
        f.write(filename)
    return redirect(url_for('admin'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/prayers')
def get_prayers():
    city = request.args.get('city', 'Khartoum')
    try:
        res = requests.get(f'https://api.aladhan.com/v1/timingsByCity?city={city}&country=Sudan&method=2', timeout=8)
        data = res.json()['data']
        timings = data['timings']
        date = data['date']
        return jsonify({
            'timings': {'الفجر': timings['Fajr'], 'الشروق': timings['Sunrise'], 'الظهر': timings['Dhuhr'], 'العصر': timings['Asr'], 'المغرب': timings['Maghrib'], 'العشاء': timings['Isha']},
            'hijri': f"{date['hijri']['day']} {date['hijri']['month']['ar']} {date['hijri']['year']} هـ",
            'gregorian': f"{date['gregorian']['day']} {date['gregorian']['month']['en']} {date['gregorian']['year']} م"
        })
    except:
        return jsonify({'error': 'فشل جلب المواقيت'}), 200

@app.route('/api/quran/<int:surah_id>')
def get_quran(surah_id):
    try:
        res = requests.get(f'https://api.alquran.cloud/v1/surah/{surah_id}/quran-uthmani', timeout=8)
        data = res.json()['data']
        return jsonify({
            'surah_name': data['name'],
            'first_ayah': data['ayahs'][0]['text'],
            'audio_url': f"https://server8.mp3quran.net/afs/{surah_id:03d}.mp3"
        })
    except:
        return jsonify({'error': 'فشل جلب القرآن'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
