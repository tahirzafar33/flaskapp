from flask import Flask, request, jsonify, Response, render_template
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError, UserNotFound
import time
import random
import threading
import logging
import os
import datetime

app = Flask(__name__, static_folder='static', template_folder='templates')
bot_running = False
stop_event = threading.Event()
log_store = []  # Persistent storage for all logs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('InstagramBot')

class LogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_store.append(log_entry)
        print(log_entry)  # Still log to console

handler = LogHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(handler)

@app.route('/')
def index():
    return render_template('index.html')

def random_typo(message):
    if random.random() < 0.2:  # 20% chance of typo
        pos = random.randint(0, len(message) - 1)
        message = message[:pos] + random.choice('abcdefghijklmnopqrstuvwxyz') + message[pos+1:]
    return message

def human_delay(min_delay=1, max_delay=5):
    time.sleep(random.uniform(min_delay, max_delay))

def run_bot(username, password, usernames, messages, start_time, daily_count, use_schedule):
    global bot_running
    bot_running = True
    logger.info("Bot initialized.")

    cl = Client()
    cl.delay_range = [1, 3]

    session_file = f"session_{username}.json"
    try:
        if os.path.exists(session_file):
            cl.load_settings(session_file)
            logger.info("Loaded existing session.")
        cl.login(username, password)
        cl.dump_settings(session_file)
        logger.info(f"Login successful for {username}!")
    except LoginRequired:
        logger.error("Login failed: Invalid credentials or 2FA required.")
        bot_running = False
        return
    except ClientError as e:
        logger.error(f"Login failed: {str(e)}")
        bot_running = False
        return

    def execute_bot_run():
        daily_users = random.sample(usernames, min(daily_count, len(usernames)))
        for target_user in daily_users:
            if stop_event.is_set():
                break
            try:
                user_id = cl.user_id_from_username(target_user)
                user_info = cl.user_info(user_id)

                medias = cl.user_medias(user_id, amount=1)
                if medias:
                    media = medias[0]
                    cl.media_like(media.pk)
                    logger.info(f"Liked first post (pk={media.pk}) for {target_user}")
                else:
                    logger.info(f"No posts found for {target_user}")

                message = random_typo(random.choice(messages))
                cl.direct_send(message, user_ids=[user_id])
                logger.info(f"Sent DM to {target_user}: {message}")
                human_delay()
            except UserNotFound:
                logger.error(f"User {target_user} not found.")
            except ClientError as e:
                logger.error(f"Error processing {target_user}: {str(e)}")
                human_delay(5, 10)

        logger.info("Run completed.")

    if use_schedule:
        logger.info("Waiting for scheduled time...")
        while bot_running and not stop_event.is_set():
            now = datetime.datetime.now()
            start_hour, start_minute = map(int, start_time.split(':'))
            start_dt = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            if now >= start_dt and now < start_dt + datetime.timedelta(minutes=60):
                logger.info(f"Starting scheduled run at {start_time}...")
                execute_bot_run()
                logger.info("Waiting for tomorrow...")
                time.sleep(24 * 60 * 60)
            else:
                time.sleep(60)
    else:
        logger.info("Starting immediate run...")
        execute_bot_run()

    logger.info("Bot stopped.")
    bot_running = False

@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    global stop_event
    if bot_running:
        return jsonify({"error": "Bot is already running!"}), 400
    data = request.json
    stop_event.clear()
    bot_thread = threading.Thread(target=run_bot, args=(
        data['username'], data['password'], data['usernames'], data['messages'],
        data.get('startTime', None), data['dailyCount'], data['useSchedule']
    ))
    bot_thread.start()
    return jsonify({"message": "Bot started successfully!"})

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    global bot_running
    if not bot_running:
        return jsonify({"error": "Bot is not running!"}), 400
    stop_event.set()
    bot_running = False
    return jsonify({"message": "Bot stopped successfully!"})

@app.route('/api/logs')
def stream_logs():
    def generate_logs():
        last_index = len(log_store)
        while bot_running or last_index < len(log_store):
            while last_index < len(log_store):
                yield f"data: {log_store[last_index]}\n\n"
                last_index += 1
            time.sleep(1)  # Wait for new logs
    return Response(generate_logs(), mimetype='text/event-stream')

@app.route('/api/all_logs', methods=['GET'])
def get_all_logs():
    return jsonify({"logs": log_store})

if __name__ == '__main__':
    app.run(debug=True)