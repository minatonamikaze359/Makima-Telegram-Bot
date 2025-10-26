from flask import Flask, render_template, redirect, url_for, request
import sqlite3, os
app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_data.sqlite3')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT user_id, username, is_premium, whatsapp_verified, balance FROM users ORDER BY user_id DESC LIMIT 200')
    users = cur.fetchall()
    cur.execute('SELECT id, user_id, file_id, timestamp, processed FROM whatsapp_proofs ORDER BY timestamp DESC LIMIT 200')
    proofs = cur.fetchall()
    conn.close()
    return render_template('index.html', users=users, proofs=proofs)

@app.route('/approve/<int:proof_id>')
def approve(proof_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT user_id FROM whatsapp_proofs WHERE id = ? AND processed = 0', (proof_id,))
    r = cur.fetchone()
    if r:
        uid = r['user_id']
        cur.execute('UPDATE whatsapp_proofs SET processed = 1 WHERE id = ?', (proof_id,))
        cur.execute('UPDATE users SET whatsapp_verified = 1 WHERE user_id = ?', (uid,))
        conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/reject/<int:proof_id>')
def reject(proof_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute('UPDATE whatsapp_proofs SET processed = 1 WHERE id = ?', (proof_id,))
    conn.commit(); conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(port=5001, debug=True)
