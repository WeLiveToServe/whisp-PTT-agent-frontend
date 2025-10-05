import logging
import time
import whisp_server_redline as server

logging.basicConfig(level=logging.INFO)

try:
    server.recorder_service.start()
    print('started ok')
    time.sleep(1.0)
    result = server.recorder_service.stop()
    print('stop result:', result)
except Exception as exc:
    import traceback
    traceback.print_exc()