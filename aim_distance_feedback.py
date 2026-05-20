import time
import math
import statistics
import requests
import RPi.GPIO as GPIO

# ============================================================
# Raspberry Pi Distance-Based Aim Guide Simulator
# ------------------------------------------------------------
# 동작 방식:
# 1. 코드에는 BOT_TOKEN만 직접 입력한다.
# 2. 최초 1회 텔레그램 봇에게 /start 또는 아무 메시지를 보낸다.
# 3. 라즈베리파이가 getUpdates로 chat_id를 자동 획득한다.
# 4. chat_id를 telegram_chat_id.txt 파일에 저장한다.
# 5. 이후부터는 버튼을 누를 때마다 거리 측정 결과를 자동 전송한다.
#
# 주의:
# - 실제 명중 보정용 X
# ============================================================


# =========================
# Telegram 설정
# =========================
# 예: BOT_TOKEN = "Bot father에서 설정한 개인 봇 토큰 입력"
BOT_TOKEN = "개인토큰정보입력"

CHAT_ID_FILE = "telegram_chat_id.txt"


# =========================
# GPIO 핀 설정
# =========================
TRIG = 20        # 초음파 센서 Trig: GPIO20
ECHO = 16        # 초음파 센서 Echo: GPIO16
BUTTON = 21      # 버튼: GPIO21
LED = 6          # LED: GPIO6

# 버튼 배선 기준:
# - PUD_DOWN 기준
# - 버튼 한쪽: GPIO21
# - 버튼 다른쪽: 3.3V
# - 평소 LOW, 누르면 HIGH
BUTTON_ACTIVE_STATE = GPIO.HIGH


# =========================
# 측정/시뮬레이션 설정
# =========================
SOUND_SPEED_CM_PER_SEC = 34300
MEASURE_TIMEOUT_SEC = 0.03

# 여러 번 측정 후 중앙값 사용: 초음파 센서 튐 완화
SAMPLES_PER_TRIGGER = 7
SAMPLE_DELAY_SEC = 0.04

# 교육용 가상 발사체 속도.
# 실제 장치가 아니라 시뮬레이션 파라미터이다.
VIRTUAL_PROJECTILE_SPEED_MPS = 8.0

# reticle 보정용 데모 계수.
# 실제 카메라 캘리브레이션값이 아니라 화면 표시용이다.
DEMO_PIXELS_PER_CM = 2.0
MAX_RETICLE_OFFSET_PX = 80

# 거리 측정 실패 시 LED 경고 유지 시간
FAILURE_LED_ON_SEC = 5.0


# =========================
# Telegram 함수
# =========================
def validate_bot_token():
    """
    BOT_TOKEN이 유효한지 getMe로 확인한다.
    401 Unauthorized가 나오면 토큰이 틀린 것이다.
    """
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
    """저장된 chat_id가 있으면 파일에서 읽어온다."""
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
    """chat_id를 파일에 저장한다."""
    with open(CHAT_ID_FILE, "w", encoding="utf-8") as file:
        file.write(str(chat_id))

    print(f"[Telegram] chat_id 저장 완료: {chat_id}")


def fetch_chat_id_from_updates():
    """
    getUpdates에서 가장 최근 메시지의 chat.id를 자동 획득한다.

    사용법:
    1. 프로그램 실행
    2. 텔레그램에서 봇에게 /start 또는 아무 메시지 전송
    3. 버튼을 누르거나 프로그램 시작 시 이 함수가 chat_id를 찾는다.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print("[Telegram getUpdates 오류]", response.text)
            return None

        data = response.json()
        results = data.get("result", [])

        if not results:
            print("[Telegram] 아직 수신된 메시지가 없습니다. 봇에게 /start를 먼저 보내세요.")
            return None

        # 가장 최근 update부터 역순으로 확인
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

        print("[Telegram] update는 있지만 chat.id를 찾지 못했습니다.")
        return None

    except Exception as error:
        print("[Telegram] getUpdates 실패:", error)
        return None


def get_chat_id():
    """
    1. 저장된 chat_id가 있으면 사용
    2. 없으면 getUpdates로 자동 획득
    """
    chat_id = load_saved_chat_id()
    if chat_id:
        return chat_id

    return fetch_chat_id_from_updates()


def send_telegram_message(text):
    """
    텔레그램 봇으로 메시지를 전송한다.
    CHAT_ID는 직접 입력하지 않고 자동 획득/저장된 값을 사용한다.
    """
    chat_id = get_chat_id()

    if not chat_id:
        print("[Telegram] chat_id가 없어 메시지를 전송할 수 없습니다.")
        print("[Telegram] 텔레그램에서 봇에게 /start를 한 번 보낸 뒤 다시 시도하세요.")
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


# =========================
# GPIO 초기화
# =========================
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)
    GPIO.setup(BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(LED, GPIO.OUT)

    GPIO.output(TRIG, GPIO.LOW)
    GPIO.output(LED, GPIO.LOW)
    time.sleep(0.5)


# =========================
# 거리 측정 함수
# =========================
def measure_distance_once_cm(trig, echo, timeout=MEASURE_TIMEOUT_SEC):
    """
    HC-SR04 초음파 센서로 거리 1회 측정.
    반환값: 거리(cm)
    측정 실패 시 None 반환.
    """

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
    distance_cm = pulse_duration * SOUND_SPEED_CM_PER_SEC / 2

    return distance_cm


def measure_distance_median_cm():
    """
    여러 번 측정한 뒤 유효값의 중앙값을 반환한다.
    초음파 센서값이 튀는 문제를 줄이기 위한 함수.
    """
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
# 거리 기반 계산 / 안내 함수
# =========================
def classify_distance(distance_m):
    """거리 구간을 분류한다."""
    if distance_m < 0.2:
        return "측정 불안정"
    if distance_m < 1.0:
        return "가까움"
    if distance_m < 2.0:
        return "중간"
    if distance_m < 3.0:
        return "멀음"
    return "범위 초과"


def calculate_projectile_simulation(distance_m):
    """
    단순 포물선 운동 기반 시뮬레이션 값 계산.

    단순화:
    - 공기저항 없음
    - 목표물과 장치 높이가 거의 같다고 가정
    - VIRTUAL_PROJECTILE_SPEED_MPS는 교육용 가상 속도
    """

    g = 9.81
    v0 = VIRTUAL_PROJECTILE_SPEED_MPS

    # 수평 방향 기준 가상 비행 시간과 낙차
    flight_time_sec = distance_m / v0
    drop_m = 0.5 * g * (flight_time_sec ** 2)

    # 같은 높이에서의 사거리 공식:
    # R = v0^2 * sin(2θ) / g
    # θ = 1/2 * asin(gR / v0^2)
    asin_arg = (g * distance_m) / (v0 ** 2)

    if 0 <= asin_arg <= 1:
        recommended_angle_deg = math.degrees(0.5 * math.asin(asin_arg))
    else:
        recommended_angle_deg = None

    return {
        "flight_time_sec": flight_time_sec,
        "drop_cm": drop_m * 100,
        "recommended_angle_deg": recommended_angle_deg,
    }


def make_aim_guide(distance_m, simulation):
    """
    거리와 포물선 시뮬레이션 결과를 바탕으로 보정 안내 생성.
    실제 명중 보정이 아니라 거리 기반 데모 안내이다.
    """
    level = classify_distance(distance_m)
    drop_cm = simulation["drop_cm"]
    angle_deg = simulation["recommended_angle_deg"]

    reticle_offset_px = min(
        int(drop_cm * DEMO_PIXELS_PER_CM),
        MAX_RETICLE_OFFSET_PX
    )

    if level == "측정 불안정":
        guide = "물체가 너무 가깝습니다. 센서와 목표물 사이 거리를 조금 더 확보하세요."
    elif level == "가까움":
        guide = "가까운 거리입니다. 조준선 보정은 거의 필요하지 않습니다."
    elif level == "중간":
        guide = "중간 거리입니다. 화면 기준 조준선을 약간 위쪽으로 보정하세요."
    elif level == "멀음":
        guide = "먼 거리입니다. 낙차가 커지므로 조준선을 더 위쪽으로 보정하세요."
    else:
        guide = "범위 초과입니다. 초음파 센서 오차가 커질 수 있으니 목표물 위치와 센서 방향을 확인하세요."

    if angle_deg is None:
        angle_text = "계산 범위 초과"
    else:
        angle_text = f"{angle_deg:.1f}°"

    return {
        "level": level,
        "reticle_offset_px": reticle_offset_px,
        "angle_text": angle_text,
        "guide": guide,
    }


def build_result_message(distance_cm):
    """
    측정 거리 기반으로 콘솔/텔레그램에 보낼 메시지를 만든다.
    """
    distance_m = distance_cm / 100.0
    simulation = calculate_projectile_simulation(distance_m)
    aim = make_aim_guide(distance_m, simulation)

    message = (
        "[거리 측정 및 보정 안내]\n\n"
        f"- 측정 거리: {distance_m:.2f} m ({distance_cm:.1f} cm)\n"
        f"- 거리 구간: {aim['level']}\n"
        f"- 가상 비행 시간: {simulation['flight_time_sec']:.3f} s\n"
        f"- 예상 낙차: {simulation['drop_cm']:.1f} cm\n"
        f"- 가상 보정 각도: {aim['angle_text']}\n"
        f"- Reticle 보정값: 위쪽으로 {aim['reticle_offset_px']} px\n"
        f"- 보정 안내: {aim['guide']}\n\n"
    )

    return message


# =========================
# LED 경고 함수
# =========================
def turn_on_failure_led(duration_sec=FAILURE_LED_ON_SEC):
    """
    Echo 신호 미수신 또는 거리 측정 실패 시에만 LED를 일정 시간 켠다.
    정상 측정 성공 시에는 LED를 켜지 않는다.
    """
    print(f"[LED] 측정 실패 경고: LED를 {duration_sec:.1f}초 동안 켭니다.")
    GPIO.output(LED, GPIO.HIGH)
    time.sleep(duration_sec)
    GPIO.output(LED, GPIO.LOW)
    print("[LED] 측정 실패 경고 종료: LED OFF")


# =========================
# 버튼 1회 = 측정 1회
# =========================
def handle_one_measurement():
    """거리 1회 측정 후 콘솔 출력 및 텔레그램 전송."""
    print("\n[버튼] 측정 트리거 감지")

    # 정상 측정에서는 LED를 켜지 않는다.
    # Echo 신호 미수신/측정 실패일 때만 아래에서 5초간 LED를 켠다.
    GPIO.output(LED, GPIO.LOW)

    distance_cm = measure_distance_median_cm()

    if distance_cm is None:
        message = (
            "[거리 측정 실패]\n\n"
            "- Echo 신호를 정상적으로 받지 못했습니다.\n"
            "- 센서 배선, 전원, 목표물 방향을 확인하세요.\n"
            "- 목표물은 크고 평평한 물체를 사용하는 것이 좋습니다.\n"
            "- 실패 알림으로 LED가 5초간 켜집니다."
        )

        print("\n" + message + "\n")
        send_telegram_message(message)

        # 측정 실패인 경우에만 LED 5초 점등
        turn_on_failure_led()

    else:
        message = build_result_message(distance_cm)
        print("\n" + message + "\n")
        send_telegram_message(message)

        # 정상 측정 성공 시 LED OFF 유지
        GPIO.output(LED, GPIO.LOW)


def wait_for_button_and_measure():
    """
    버튼이 눌릴 때마다 거리 1회 측정 후 텔레그램 전송.
    ON/OFF 토글이 아니라 버튼 입력 자체가 측정 트리거이다.
    """
    print("프로그램 시작")
    print("버튼을 누르면 거리 측정이 딱 한 번 실행되고 결과가 텔레그램으로 전송됩니다.")
    print("처음 실행 시 봇에게 /start를 한 번 보내면 chat_id가 자동 저장됩니다.")
    print("종료하려면 Ctrl+C를 누르세요.")

    if not validate_bot_token():
        print("[중단] BOT_TOKEN이 올바르지 않아 프로그램을 종료합니다.")
        return

    # 시작 시 chat_id 자동 확인 시도
    chat_id = get_chat_id()
    if chat_id:
        send_telegram_message("라즈베리파이 거리 측정 보정 시뮬레이터가 시작되었습니다.")
    else:
        print("[Telegram] 아직 chat_id가 없습니다.")
        print("[Telegram] 텔레그램에서 봇에게 /start를 보낸 뒤 버튼을 누르면 자동 저장됩니다.")

    last_state = GPIO.LOW

    while True:
        current_state = GPIO.input(BUTTON)

        # LOW -> HIGH가 되는 순간을 버튼 입력으로 인식
        if current_state == BUTTON_ACTIVE_STATE and last_state != BUTTON_ACTIVE_STATE:
            time.sleep(0.05)

            if GPIO.input(BUTTON) == BUTTON_ACTIVE_STATE:
                handle_one_measurement()

                # 버튼을 계속 누르고 있어도 한 번만 측정
                while GPIO.input(BUTTON) == BUTTON_ACTIVE_STATE:
                    time.sleep(0.01)

        last_state = current_state
        time.sleep(0.01)


def main():
    setup_gpio()

    try:
        wait_for_button_and_measure()
    except KeyboardInterrupt:
        print("\n프로그램 수동 종료")
    finally:
        GPIO.output(LED, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO 정리 완료")


if __name__ == "__main__":
    main()
