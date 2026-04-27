import socket
import threading
import sys
import time
import queue
import readchar
import os
import random
from volcenginesdkarkruntime import Ark

# ================= AI 配置 (来自 LLM.py) =================
client = Ark(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key="ark-57110cb9-7c1b-4d16-bdb7-2a0e20cc00c5-5a859" 
)

def call_llm(user_msg, username):
    try:
        completion = client.chat.completions.create(
            model="ep-20260427174930-ltxqs", 
            messages=[
                {
                    "role": "system", 
                    "content": (
                        f"You are a chat user named {username}. "
                        "RULES: 1. Be extremely brief (under 15 words). "
                        "2. Speak naturally/casually in English like a real person. "
                        "3. Talk about school life (diversity and creativity, many topics). "
                        "4. NEVER repeat the same content as others or yourself. "
                        "5. Your responses should be diverse and creative."
                        "6. Sometimes open a new topic in reply, but still related to school life. "
                        "7. No emojis or special symbols. Just plain text. "
                        "8. Less 'What's up','How about you?'-type generic greetings. Be more specific and creative. "
                        "9. You can just reply with a single word if you want, but it must be relevant and interesting. "
                    )
                },
                {"role": "user", "content": user_msg}
            ],
            temperature=0.9
        )
        return completion.choices[0].message.content.strip()
    except Exception:
        return None

# ================= 全局变量 (完全保留 client.py) =================
debug = False
SERVER_IP = "127.0.0.1"
SERVER_PORT = 9000
USERNAME = ""
MAX_MESSAGE_LENGTH = 1 << 20

leave = False
PRINT_MESSAGE = queue.Queue()
SEND_MESSAGE = queue.Queue()
AI_INBOX = queue.Queue() # 新增：AI 专用收件箱

MESSAGE_ESCAPE = "*"
CODE_ESCAPE = "_"
END_ESCAPE = "\t"  # end sign of a message
ACK_INTERVAL = 4  # send ack per 4 seconds
TIMEOUT_LIMIT = 10
EXIT_CODE = 0  # 0=ctrl+c 1=abnormal exit

theme_color = 28  # preferred color
theme_color2 = 18  # preferred color 2
theme_color3 = 12  # preferred color 3

color_pairs = [
    "\033[38;5;196m", "\033[38;5;197m", "\033[38;5;198m", "\033[38;5;199m", "\033[38;5;200m",
    "\033[38;5;201m", "\033[38;5;202m", "\033[38;5;203m", "\033[38;5;204m", "\033[38;5;205m",
    "\033[38;5;206m", "\033[38;5;208m", "\033[38;5;209m", "\033[38;5;210m", "\033[38;5;211m",
    "\033[38;5;212m", "\033[38;5;214m", "\033[38;5;215m", "\033[38;5;216m", "\033[38;5;217m",
    "\033[38;5;218m", "\033[38;5;220m", "\033[38;5;221m", "\033[38;5;222m", "\033[38;5;223m",
    "\033[38;5;190m", "\033[38;5;154m", "\033[38;5;118m", "\033[38;5;82m", "\033[38;5;46m",
]

def coloring(x, k):
    global color_pairs
    return color_pairs[k] + x + "\033[0m"

# ================= UI 类 (完全保留 client.py) =================
class ChatUI:
    def __init__(self):
        self._running = False
        self._lock = threading.Lock()
        self._buffer = []
        self._prompt = coloring("> ", theme_color3)

    def start(self):
        self._running = True
        self._input_loop()

    def push_message(self, msg):
        with self._lock:
            self._clear_line()  # clear the user line
            if msg == f"Welcome {USERNAME} to the chatroom!":
                print(f"Welcome {coloring(USERNAME, theme_color3)} to the chatroom!")
            elif msg[: len(USERNAME)] == USERNAME:
                print(coloring(USERNAME, theme_color3) + msg[len(USERNAME) :])
            else:
                print(msg)
            print()  # add a empty line after each push
            self._render_prompt()  # rerender the user line

    def _input_loop(self):
        global leave, EXIT_CODE
        while not leave:
            try:
                ch = readchar.readchar()
            except KeyboardInterrupt:
                leave = True
                SEND_MESSAGE.put("__EXIT__")
                EXIT_CODE = 0
                break

            if ch == "\x03":  # Ctrl+C
                leave = True
                SEND_MESSAGE.put("__EXIT__")
                print("\nExiting...")
                EXIT_CODE = 0
                break

            with self._lock:
                if ch == "\x03":
                    leave = True
                    SEND_MESSAGE.put("__EXIT__")
                    break

                elif ch == readchar.key.ENTER:
                    if not self._buffer: continue
                    msg = "".join(self._buffer)
                    self._clear_line()
                    self._buffer.clear()
                    if msg.strip():
                        SEND_MESSAGE.put(MESSAGE_ESCAPE + msg)
                    self._render_prompt()

                elif ch == readchar.key.BACKSPACE:
                    if self._buffer:
                        self._buffer.pop()
                        self._clear_line()
                        self._render_prompt()

                else:
                    self._buffer.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()

        if debug:
            print("\033[48;5;136mDEBUG\033[0m Leaving UI")

    def _clear_line(self):
        col = os.get_terminal_size().columns
        clear_len = 2 + len(self._buffer)
        sys.stdout.write("\r\033[K")  # 清除该行
        for i in range(-1 + (clear_len // col) + 1 if ((clear_len % col) > 0) else 0):
            sys.stdout.write("\033[A")  # 光标上移一行
            sys.stdout.write("\r\033[K")  # 清除该行

    def _render_prompt(self):
        sys.stdout.write("\r")
        sys.stdout.write(self._prompt + "".join(self._buffer))
        sys.stdout.flush()

# ================= 逻辑线程 (整合 AI 消息提取) =================

def listen(sock):
    global leave, debug, EXIT_CODE
    sock.settimeout(TIMEOUT_LIMIT)
    while True:
        try:
            data = sock.recv(MAX_MESSAGE_LENGTH)
        except socket.timeout:
            leave = True
            EXIT_CODE = 2
            break

        if not data: break
        data = data.decode()

        if debug:
            PRINT_MESSAGE.put("\033[48;5;136mDEBUG\033[0m " + data)

        for msg in data.split(END_ESCAPE):
            if msg == "": continue

            escape = msg[0:1]

            if escape == CODE_ESCAPE:
                if msg == "__KICK__":
                    leave = True
                    print("You are offline now. Quiting the chatroom..")
                    EXIT_CODE = 1
                    exit(0)
                if msg == "__ACK__" and debug:
                    PRINT_MESSAGE.put("\033[48;5;136mDEBUG\033[0m Recieved online ACK from server")

            elif escape == MESSAGE_ESCAPE:
                msg_content = msg[1:]
                for m in msg_content.split(END_ESCAPE):
                    if m.strip():
                        PRINT_MESSAGE.put(m)
                        AI_INBOX.put(m) # 核心：将所有收到的聊天消息喂给 AI
            else:
                if debug:
                    PRINT_MESSAGE.put("\033[48;5;136mDEBUG\033[0m \033[48;5;196mMessage Corrupted\033[0m Received: " + msg)

    leave = True
    PRINT_MESSAGE.put("Disconnected from server.")

def send(sock):
    global leave
    while True:
        msg = SEND_MESSAGE.get()
        try:
            sock.send((msg + END_ESCAPE).encode())
        except: break

def onlineACK(sock):
    while True:
        try:
            sock.send(("__ACK__").encode())
        except: break
        time.sleep(ACK_INTERVAL)

def write(ui):
    global leave
    while True:
        msg = PRINT_MESSAGE.get()
        ui.push_message(msg)
        if leave: break

# ================= AI 自动回复逻辑 (来自 LLM.py) =================
def ai_worker():
    global leave
    time.sleep(3) 
    
    # 模拟上线招呼
    welcome_reply = call_llm(f"Greet everyone briefly as {USERNAME}. Be casual.", USERNAME)
    if welcome_reply:
        time.sleep(random.uniform(2, 4))
        SEND_MESSAGE.put(MESSAGE_ESCAPE + welcome_reply)

    while not leave:
        msg = AI_INBOX.get()
        if ":" not in msg: continue
            
        try:
            sender, content = msg.split(":", 1)
            sender = sender.strip()
            # 过滤掉系统消息和自己的消息
            if sender == USERNAME or "Welcome" in msg:
                continue
            
            # AI 调用
            reply = call_llm(content.strip(), USERNAME)
            if reply:
                # 动态延迟核心算法
                think_time = random.uniform(1.5, 3.0)
                typing_speed = random.uniform(0.08, 0.14)
                typing_time = len(reply) * typing_speed
                total_wait = think_time + typing_time
                
                time.sleep(min(total_wait, 10.0))
                SEND_MESSAGE.put(MESSAGE_ESCAPE + reply)
        except Exception:
            continue

# ================= 主程序 (完全保留 client.py 交互细节) =================

def enter_prompt1():
    global SERVER_IP, SERVER_PORT, theme_color, theme_color2
    print(f"Enter Server {coloring('IP', theme_color)} (press Enter to use default configuration {coloring(SERVER_IP, theme_color)}):", end=" ")
    x = input()
    if x != "": SERVER_IP = x
    while True:
        try:
            print(f"Enter Server {coloring('PORT', theme_color2)} (press Enter to use default configuration {coloring(str(SERVER_PORT), theme_color2)}):", end=" ")
            x = input()
            if x != "": SERVER_PORT = int(x)
            break
        except ValueError:
            print("Please use \033[48;5;213mINT\033[0m type input!")
    print(f"Your setting now is {coloring(SERVER_IP, theme_color)}:{coloring(str(SERVER_PORT), theme_color2)}")

def main():
    global leave, theme_color, theme_color2, SERVER_IP, SERVER_PORT, USERNAME, EXIT_CODE

    try:
        while True:
            SERVER_IP = "127.0.0.1"
            SERVER_PORT = 9000
            enter_prompt1()
            s = socket.socket()
            print("Prepare to connect...")
            try:
                s.connect((SERVER_IP, SERVER_PORT))
                break
            except ConnectionRefusedError:
                print("\033[48;5;196mFailed to connect to server!\033[0m")
            except (OSError, OverflowError, ValueError):
                print("\033[48;5;196mWrong format!\033[0m")
        print(f"\033[48;5;35mConnected to server\033[0m {coloring(SERVER_IP, theme_color)}:{coloring(str(SERVER_PORT), theme_color2)}")
    except KeyboardInterrupt:
        print("\n\033[48;5;213mCtrl+C\033[0m captured! Quit the chatroom.")
        exit(0)

    try:
        while True:
            USERNAME = ""
            while USERNAME == "": 
                USERNAME = input("Enter your username: ")
            data = ""
            while data != "__NAMEACCEPTED__" and data != "__NAMEREJECTED__":
                s.send(USERNAME.encode())
                try:
                    s.settimeout(2.0)
                    data = s.recv(1024).decode()
                except socket.timeout:
                    s.settimeout(None)
                    if debug: print("\033[48;5;136mDEBUG\033[0m Timeout when receiving the name")
                if debug: print("\033[48;5;136mDEBUG\033[0m Retransmission of name, received: " + data)
            s.settimeout(None)
            if data == "__NAMEACCEPTED__": break
            print("Please enter your name again. This problem might occur because there is the same name in the chatroom.")
    except KeyboardInterrupt:
        print("\n\033[48;5;213mCtrl+C\033[0m captured! Quit the chatroom.")
        exit(0)

    # 开启线程
    threading.Thread(target=listen, args=(s,), daemon=True).start()
    threading.Thread(target=send, args=(s,), daemon=True).start()
    threading.Thread(target=onlineACK, args=(s,), daemon=True).start()
    threading.Thread(target=ai_worker, daemon=True).start() # AI 线程

    ui = ChatUI()
    threading.Thread(target=write, args=(ui,), daemon=True).start()

    ui.start()  # main thread

    if EXIT_CODE == 0:
        print("\033[48;5;213mCtrl+C\033[0m captured! Quit the chatroom!")
    elif EXIT_CODE == 1:
        print("You are now quiting the chatroom because the server kicks you off.")
    elif EXIT_CODE == 2:
        print("You are now quiting the chatroom because the server is dead.")

    s.close()
    leave = True

if __name__ == "__main__":
    main()
