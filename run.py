import os
import socket
from app import create_app

env = os.getenv("FLASK_ENV", "development")
app = create_app(env)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = get_local_ip()
    print("\n" + "="*55)
    print("  LALBAGH ENTERPRISE — IMS")
    print("="*55)
    print(f"  Local:   http://localhost:5000")
    print(f"  Network: http://{ip}:5000")
    print(f"\n  Share http://{ip}:5000 with any device on WiFi")
    print("="*55 + "\n")
    app.run(debug=(env == "development"), host="0.0.0.0", port=5000)