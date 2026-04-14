import requests

BASE_URL = "http://localhost:8000"


def build_alternating_backcourt_shots(total_shots=10):
    """Build a left/right alternating backcourt sequence for API testing."""
    shots = []
    for i in range(total_shots):
        is_left = (i % 2 == 0)
        side = "left" if is_left else "right"

        shots.append(
            {
                "speed": 50.0,
                "yaw": -7.0 if is_left else 7.0,
                "pitch": 30.0,
                "delay_ms": 1200,
                "description": f"Backcourt {side} #{i + 1}",
            }
        )

    return shots

def test_machine_status():
    response = requests.get(f"{BASE_URL}/machine/machine_status")
    print("Status:", response.json())

def test_start_program():
    shots = build_alternating_backcourt_shots(total_shots=10)

    payload = {
        "call_id": "python-test-alt-backcourt-10",
        "shots": shots,
        "repeat": 1,
        "meta": {
            "menuName": "Alternating Backcourt x10",
            "description": "Alternating left/right backcourt for 10 total shots",
        }
    }

    response = requests.post(f"{BASE_URL}/machine/start_program", json=payload)
    print("Start Program:", response.json())

def test_pause():
    response = requests.post(f"{BASE_URL}/machine/pause_program")
    print("Pause:", response.json())

def test_resume():
    response = requests.post(f"{BASE_URL}/machine/resume_program")
    print("Resume:", response.json())

def test_stop():
    response = requests.post(f"{BASE_URL}/machine/stop_program")
    print("Stop:", response.json())

if __name__ == "__main__":
    test_machine_status()
    test_start_program()
    # Uncomment to test controls
    # test_pause()
    # test_resume()
    # test_stop()