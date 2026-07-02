# import logging
# import sys


# def setup_logger(log_file='scheduling_log.txt'):
#     logger = logging.getLogger()
#     logger.setLevel(logging.INFO)

#     # Clear existing handlers (avoid duplication if re-run)
#     if logger.hasHandlers():
#         logger.handlers.clear()

#     file_handler = logging.FileHandler(log_file, mode='w')
#     formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)

#     return logger




# class StreamToLogger:
#     """
#     Redirect writes to a logger instance instead of the console.
#     """
#     def __init__(self, logger, log_level=logging.INFO):
#         self.logger = logger
#         self.log_level = log_level
#         self.linebuf = ""

#     def write(self, buf):
#         for line in buf.rstrip().splitlines():
#             self.logger.log(self.log_level, line.rstrip())

#     def flush(self):
#         pass


# def setup_logger(log_file='scheduling_log.txt'):
#     logger = logging.getLogger()
#     logger.setLevel(logging.INFO)

#     if logger.hasHandlers():
#         logger.handlers.clear()

#     file_handler = logging.FileHandler(log_file, mode='w')
#     formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)

#     #Optional: mirror print() to file
#     sys.stdout = StreamToLogger(logger, logging.INFO)
#     sys.stderr = StreamToLogger(logger, logging.ERROR)

#     return logger

# import logging
# import sys
# from datetime import datetime
# import os

# class StreamToLogger:
#     def __init__(self, logger, log_level=logging.INFO):
#         self.logger = logger
#         self.log_level = log_level
#         self._internal_write = False

#     def write(self, message):
#         if self._internal_write:
#             return
#         message = message.strip()
#         if message:
#             try:
#                 self._internal_write = True
#                 self.logger.log(self.log_level, message)
#             finally:
#                 self._internal_write = False

#     def flush(self):
#         pass

# def setup_logger(log_dir='logs'):
#     # Create log directory if it doesn't exist
#     os.makedirs(log_dir, exist_ok=True)

#     # Generate filename with timestamp
#     timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
#     log_filename = os.path.join(log_dir, f"log_{timestamp}.txt")

#     logger = logging.getLogger()
#     logger.setLevel(logging.INFO)

#     if logger.hasHandlers():
#         logger.handlers.clear()

#     file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
#     formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)

#     # Redirect stdout and stderr
#     sys.stdout = StreamToLogger(logger, logging.INFO)
#     sys.stderr = StreamToLogger(logger, logging.ERROR)

#     return logger

# import logging
# import sys
# from datetime import datetime
# import os

# class StreamToLogger:
#     def __init__(self, logger, log_level=logging.INFO):
#         self.logger = logger
#         self.log_level = log_level
#         self._internal_write = False

#     def write(self, message):
#         if self._internal_write:
#             return
#         message = message.strip()
#         if message:
#             try:
#                 self._internal_write = True
#                 self.logger.log(self.log_level, message)
#             finally:
#                 self._internal_write = False

#     def flush(self):
#         pass

# def setup_logger(base_log_dir='logs', timestamp=None):
#     if timestamp is None:
#         timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
#     log_dir = os.path.join(base_log_dir, timestamp)
#     os.makedirs(log_dir, exist_ok=True)

#     log_filename = os.path.join(log_dir, "system_ga_log.txt")

#     logger = logging.getLogger()
#     logger.setLevel(logging.INFO)

#     if logger.hasHandlers():
#         logger.handlers.clear()

#     file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
#     formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)

#     sys.stdout = StreamToLogger(logger, logging.INFO)
#     sys.stderr = StreamToLogger(logger, logging.ERROR)

#     return logger, log_dir, timestamp


import logging
import os
import sys
from datetime import datetime
import shutil

class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

def setup_logger(base_log_dir='logs', timestamp=None):
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_dir = os.path.join(base_log_dir, timestamp)
    os.makedirs(log_dir, exist_ok=True)

    log_filename = os.path.join(log_dir, "system_ga_log.txt")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    sys.stdout = StreamToLogger(logger, logging.INFO)
    sys.stderr = StreamToLogger(logger, logging.ERROR)

    # ✅ Copy config.py for reproducibility
    try:
        config_source = os.path.join(os.getcwd(), "config.py")
        config_dest = os.path.join(log_dir, "config.py")
        shutil.copyfile(config_source, config_dest)
        logger.info(f"[Logger] config.py snapshot saved to: {config_dest}")
    except Exception as e:
        logger.warning(f"[Logger] Could not copy config.py: {e}")

    return logger, log_dir, timestamp
