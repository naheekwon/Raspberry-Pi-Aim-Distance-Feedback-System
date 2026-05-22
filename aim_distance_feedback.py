import time
import math
import statistics
import requests
import os
from datetime import datetime

import cv2
import RPi.GPIO as GPIO

# ============================================================
# Raspberry Pi Distance-Based Aim Guide Simulator
# ============================================================

# =========================
# Telegram 설정
# =========================
BOT_TOKEN = "여기에_텔레그램_봇_토큰_입력"

CHAT_ID_FILE = "telegram_chat_id.txt"

# =========================
# GPIO 핀 설정
# =========================
TRIG = 20
ECHO = 16
BUTTON = 21
LED = 6

BUTTON_ACTIVE_STATE = GPIO.HIGH

# =========================
# 측정 설정
# =========================
SOUND_SPEED_CM_PER_SEC = 34300
MEASURE_TIMEOUT_SEC = 0.03

SAMPLES_PER_TRIGGER = 7
SAMPLE_DELAY_SEC = 0.04

FAILURE_LED_ON_SEC = 5.0

# =========================
# Webcam 설정
# =========================
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_WARMUP_FRAMES = 8

CAPTURE_DIR = "captures"

# =========================
# Telegram 함수
# =========================
def validate_bot_token():

    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("[Telegram] BOT_TOKEN이 설정되지 않았습니다.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print("[Telegram 토큰 오류]", response.text)
            return False

        data = response.json()

        if not data.get("ok"):
            print("[Telegram 토큰 오류]", data)
            return False

        bot_name = data.get("result", {}).get("username", "unknown")

        print(f"[Telegram] 봇 토큰 확인 완료: @{bot_name}")
        return True

    except Exception as error:
        print("[Telegram] 토큰 확인 실패:", error)
        return False


def load_saved_chat_id():

    try:
        with open(CHAT_ID_FILE, "r", encoding="utf-8") as file:
            chat_id = file.read().strip()

        if chat_id:
            print(f"[Telegram] 저장된 chat_id 사용: {chat_id}")
            return chat_id

    except FileNotFoundError:
        pass

    return None


def save_chat_id(chat_id):

    with open(CHAT_ID_FILE, "w", encoding="utf-8") as file:
        file.write(str(chat_id))

    print(f"[Telegram] chat_id 저장 완료: {chat_id}")


def fetch_chat_id_from_updates():

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print("[Telegram getUpdates 오류]", response.text)
            return None

        data = response.json()
        results = data.get("result", [])

        if not results:
            print("[Telegram] 봇에게 /start 를 먼저 보내세요.")
            return None

        for update in reversed(results):

            message = update.get("message") or update.get("edited_message")

            if not message:
                continue

            chat = message.get("chat")

            if not chat:
                continue

            chat_id = chat.get("id")

            if chat_id is not None:
                save_chat_id(chat_id)
                return str(chat_id)

        return None

    except Exception as error:
        print("[Telegram] getUpdates 실패:", error)
        return None


def get_chat_id():

    chat_id = load_saved_chat_id()

    if chat_id:
        return chat_id

    return fetch_chat_id_from_updates()


def send_telegram_message(text):

    chat_id = get_chat_id()

    if not chat_id:
        print("[Telegram] chat_id 없음")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": chat_id,
        "text": text,
    }

    try:
        response = requests.post(url, data=data, timeout=5)

        if response.status_code != 200:
            print("[Telegram 전송 오류]", response.text)
            return False

        print("[Telegram] 메시지 전송 완료")
        return True

    except Exception as error:
        print("[Telegram] 메시지 전송 실패:", error)
        return False


def send_telegram_photo(image_path, caption):

    chat_id = get_chat_id()

    if not chat_id:
        print("[Telegram] chat_id 없음")
        return False

    if not image_path or not os.path.exists(image_path):
        print("[Telegram] 이미지 없음")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    data = {
        "chat_id": chat_id,
        "caption": caption[:1000],
    }

    try:
        with open(image_path, "rb") as image_file:

            files = {
                "photo": image_file
            }

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=10
            )

        if response.status_code != 200:
            print("[Telegram 사진 전송 오류]", response.text)
            return False

        print("[Telegram] 사진 전송 완료")
        return True

    except Exception as error:
        print("[Telegram] 사진 전송 실패:", error)
        return False


# =========================
# GPIO 초기화
# =========================
def setup_gpio():

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)

    GPIO.setup(
        BUTTON,
        GPIO.IN,
        pull_up_down=GPIO.PUD_DOWN
    )

    GPIO.setup(LED, GPIO.OUT)

    GPIO.output(TRIG, GPIO.LOW)
    GPIO.output(LED, GPIO.LOW)

    time.sleep(0.5)


# =========================
# 거리 측정
# =========================
def measure_distance_once_cm(trig, echo, timeout=MEASURE_TIMEOUT_SEC):

    GPIO.output(trig, GPIO.LOW)
    time.sleep(0.000002)

    GPIO.output(trig, GPIO.HIGH)
    time.sleep(0.00001)

    GPIO.output(trig, GPIO.LOW)

    wait_start = time.time()

    while GPIO.input(echo) == GPIO.LOW:

        if time.time() - wait_start > timeout:
            return None

    pulse_start = time.time()

    while GPIO.input(echo) == GPIO.HIGH:

        if time.time() - pulse_start > timeout:
            return None

    pulse_end = time.time()

    pulse_duration = pulse_end - pulse_start

    distance_cm = (
        pulse_duration *
        SOUND_SPEED_CM_PER_SEC / 2
    )

    return distance_cm


def measure_distance_median_cm():

    values = []

    for _ in range(SAMPLES_PER_TRIGGER):

        distance_cm = measure_distance_once_cm(TRIG, ECHO)

        if distance_cm is not None and 2.0 <= distance_cm <= 400.0:
            values.append(distance_cm)

        time.sleep(SAMPLE_DELAY_SEC)

    if not values:
        return None

    return statistics.median(values)


# =========================
# 메시지
# =========================
def build_result_message(distance_cm):

    distance_m = distance_cm / 100.0

    g = 9.81
    v0 = 8.0

    flight_time_sec = distance_m / v0

    drop_m = 0.5 * g * (flight_time_sec ** 2)

    asin_arg = (g * distance_m) / (v0 ** 2)

    if 0 <= asin_arg <= 1:
        angle_deg = math.degrees(
            0.5 * math.asin(asin_arg)
        )
        angle_text = f"{angle_deg:.1f}°"
    else:
        angle_text = "계산불가"

    message = (
        "[거리 측정 결과]\n\n"
        f"거리: {distance_m:.2f}m\n"
        f"낙차(sim): {drop_m * 100:.1f}cm\n"
        f"각도(sim): {angle_text}\n\n"
        "초록색 NOW = 현재 화면 중심"
    )

    return message


# =========================
# Webcam
# =========================
def capture_webcam_frame():

    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print("[Camera] 웹캠 열기 실패")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    time.sleep(0.2)

    frame = None

    for _ in range(CAMERA_WARMUP_FRAMES):

        ret, temp = cap.read()

        if ret and temp is not None:
            frame = temp

        time.sleep(0.05)

    cap.release()

    if frame is None:
        return None

    return frame


# =========================
# 초록 NOW 표시만
# =========================
def draw_aim_overlay(frame, distance_cm):

    height, width = frame.shape[:2]

    center_x = width // 2
    center_y = height // 2

    current_center = (center_x, center_y)

    # 초록 십자선
    cv2.line(
        frame,
        (center_x - 40, center_y),
        (center_x + 40, center_y),
        (0, 255, 0),
        3
    )

    cv2.line(
        frame,
        (center_x, center_y - 40),
        (center_x, center_y + 40),
        (0, 255, 0),
        3
    )

    # 초록 중심점
    cv2.circle(
        frame,
        current_center,
        12,
        (0, 255, 0),
        -1
    )

    # NOW 텍스트
    cv2.putText(
        frame,
        "NOW",
        (center_x + 20, center_y + 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        3
    )

    return frame


# =========================
# 이미지 저장
# =========================
def capture_and_annotate_aim_image(distance_cm):

    frame = capture_webcam_frame()

    if frame is None:
        return None

    annotated_frame = draw_aim_overlay(
        frame,
        distance_cm
    )

    os.makedirs(CAPTURE_DIR, exist_ok=True)

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    image_path = os.path.join(
        CAPTURE_DIR,
        f"aim_feedback_{timestamp}.jpg"
    )

    success = cv2.imwrite(
        image_path,
        annotated_frame
    )

    if not success:
        return None

    print(f"[Camera] 저장 완료: {image_path}")

    return image_path


# =========================
# LED
# =========================
def turn_on_failure_led(duration_sec=FAILURE_LED_ON_SEC):

    GPIO.output(LED, GPIO.HIGH)

    time.sleep(duration_sec)

    GPIO.output(LED, GPIO.LOW)


# =========================
# 측정
# =========================
def handle_one_measurement():

    print("\n[버튼] 측정 시작")

    GPIO.output(LED, GPIO.LOW)

    distance_cm = measure_distance_median_cm()

    if distance_cm is None:

        message = (
            "[거리 측정 실패]\n"
            "센서를 확인하세요."
        )

        print(message)

        send_telegram_message(message)

        turn_on_failure_led()

    else:

        message = build_result_message(distance_cm)

        print(message)

        image_path = capture_and_annotate_aim_image(
            distance_cm
        )

        if image_path:
            send_telegram_photo(
                image_path,
                message
            )
        else:
            send_telegram_message(message)


# =========================
# 버튼 대기
# =========================
def wait_for_button_and_measure():

    print("프로그램 시작")

    if not validate_bot_token():
        print("[중단] BOT_TOKEN 오류")
        return

    get_chat_id()

    last_state = GPIO.LOW

    while True:

        current_state = GPIO.input(BUTTON)

        if (
            current_state == BUTTON_ACTIVE_STATE
            and
            last_state != BUTTON_ACTIVE_STATE
        ):

            time.sleep(0.05)

            if GPIO.input(BUTTON) == BUTTON_ACTIVE_STATE:

                handle_one_measurement()

                while GPIO.input(BUTTON) == BUTTON_ACTIVE_STATE:
                    time.sleep(0.01)

        last_state = current_state

        time.sleep(0.01)


# =========================
# main
# =========================
def main():

    setup_gpio()

    try:
        wait_for_button_and_measure()

    except KeyboardInterrupt:
        print("\n프로그램 종료")

    finally:

        GPIO.output(LED, GPIO.LOW)

        GPIO.cleanup()

        print("GPIO 정리 완료")


if __name__ == "__main__":
    main()
