    import socket
    import threading
    import sys
    import time
    import queue
    import readchar
    import random
    from volcenginesdkarkruntime import Ark

    # ================= AI 配置 =================
    client = Ark(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ark-57110cb9-7c1b-4d16-bdb7-2a0e20cc00c5-5a859" # 你的新Key
    )

    def call_llm(user_msg, username):
        try:
            completion = client.chat.completions.create(
                model="ep-20260427174930-ltxqs", # 你的新模型ID
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            f"You are a chat user named {username}. "
                            "RULES: 1. Be extremely brief (under 15 words). "
                            "2. Speak naturally/casually in English like a real person. "
                            "3. Talk about school life (classes, coffee, stress, exams). "
                            "4. NEVER repeat the same content as others or yourself. "
                            "5. Your responses should be diverse and creative."
                        )
                    },
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.9 # 这里设置 0.9 使回复更具随机性和多样性
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            PRINT_MESSAGE.put(f"\033[31m[AI Error]\033[0m {e}")
            return None

    # ================= 全局变量 =================
    debug = False
    SERVER_IP = "127.0.0.1"
    SERVER_PORT = 9000
    USERNAME = ""
    MAX_MESSAGE_LENGTH = 1 << 20

    leave = False
    PRINT_MESSAGE = queue.Queue()
    SEND_MESSAGE = queue.Queue()
    AI_INBOX = queue.Queue() 

    MESSAGE_ESCAPE = "*"
    CODE_ESCAPE = "_"
    END_ESCAPE = "\t"  
    ACK_INTERVAL = 4  
    TIMEOUT_LIMIT = 10
    EXIT_CODE = 0  

    theme_color = 28  
    theme_color2 = 18  
    theme_color3 = 12  

    color_pairs = [f"\033[38;5;{i}m" for i in range(196, 226)] # 简写颜色列表

    def coloring(x, k):
        return color_pairs[k] + x + "\033[0m"

    # ================= UI 框架 (完全保留) =================
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
                self._clear_line()
                if msg == f"Welcome {USERNAME} to the chatroom!":
                    print(f"Welcome {coloring(USERNAME, theme_color3)} to the chatroom!")
                elif msg.startswith(USERNAME + ":"):
                    print(coloring(USERNAME, theme_color3) + msg[len(USERNAME) :])
                else:
                    print(msg)
                self._render_prompt()

        def _input_loop(self):
            global leave, EXIT_CODE
            while not leave:
                try:
                    ch = readchar.readchar()
                except KeyboardInterrupt:
                    leave = True
                    SEND_MESSAGE.put("__EXIT__")
                    import os; os._exit(0)
                if ch == "\x03":
                    leave = True
                    SEND_MESSAGE.put("__EXIT__")
                    break

                with self._lock:
                    if ch == readchar.key.ENTER:
                        msg = "".join(self._buffer)
                        self._buffer.clear()
                        self._clear_line()
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

        def _clear_line(self):
            sys.stdout.write("\r\033[K")

        def _render_prompt(self):
            sys.stdout.write("\r")
            sys.stdout.write(self._prompt + "".join(self._buffer))
            sys.stdout.flush()

    # ================= 逻辑线程 =================

    def listen(sock):
        global leave, EXIT_CODE
        sock.settimeout(TIMEOUT_LIMIT)
        while True:
            try:
                data = sock.recv(MAX_MESSAGE_LENGTH)
                if not data: break
                data = data.decode()

                for msg in data.split(END_ESCAPE):
                    if not msg: continue
                    escape = msg[0:1]

                    if escape == CODE_ESCAPE:
                        if msg == "__KICK__":
                            leave = True
                            EXIT_CODE = 1
                    elif escape == MESSAGE_ESCAPE:
                        content = msg[1:]
                        if content.strip():
                            PRINT_MESSAGE.put(content)
                            AI_INBOX.put(content) 
            except:
                break
        leave = True

    def send(sock):
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
        while True:
            msg = PRINT_MESSAGE.get()
            ui.push_message(msg)
            if leave: break

    # ================= AI 自动回复线程 (优化延迟与多样性) =================
    def ai_worker():
        global leave
        time.sleep(3) 
        
        # 上线首条招呼
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
                content = content.strip()

                # 过滤
                if sender == USERNAME or "Welcome" in msg:
                    continue
                
                # AI 调用
                reply = call_llm(content, USERNAME)
                if reply:
                    # --- 动态延迟核心算法 ---
                    # 思考基础时间: 1.5 ~ 3 秒
                    think_time = random.uniform(1.5, 3.0)
                    # 模拟打字速度: 每个字符 0.08 ~ 0.14 秒
                    typing_speed = random.uniform(0.08, 0.14)
                    typing_time = len(reply) * typing_speed
                    
                    total_wait = think_time + typing_time
                    # 睡眠 (最高限度 10秒)
                    time.sleep(min(total_wait, 10.0))
                    
                    SEND_MESSAGE.put(MESSAGE_ESCAPE + reply)
            except Exception:
                continue

    # ================= 主程序 =================

    def enter_prompt1():
        global SERVER_IP, SERVER_PORT
        print(f"Enter Server {coloring('IP', 28)} (Enter for {SERVER_IP}):", end=" ")
        x = input().strip()
        if x: SERVER_IP = x
        while True:
            try:
                print(f"Enter Server {coloring('PORT', 18)} (Enter for {SERVER_PORT}):", end=" ")
                x = input().strip()
                if x: SERVER_PORT = int(x)
                break
            except ValueError:
                print("Please use INT!")

    def main():
        global leave, USERNAME, SERVER_IP, SERVER_PORT, EXIT_CODE

        try:
            while True:
                enter_prompt1()
                s = socket.socket()
                try:
                    s.connect((SERVER_IP, SERVER_PORT))
                    break
                except:
                    print("Connection failed!")
            print(f"Connected to {SERVER_IP}:{SERVER_PORT}")
        except KeyboardInterrupt:
            exit(0)

        try:
            while True:
                USERNAME = ""
                while not USERNAME: 
                    USERNAME = input("Enter your username: ").strip()
                s.send(USERNAME.encode())
                try:
                    s.settimeout(2.0)
                    res = s.recv(1024).decode()
                    if res == "__NAMEACCEPTED__": break
                    print("Name rejected/taken.")
                except socket.timeout:
                    print("Retrying verification...")
                finally:
                    s.settimeout(None)
        except KeyboardInterrupt:
            exit(0)

        # 启动功能线程
        threading.Thread(target=listen, args=(s,), daemon=True).start()
        threading.Thread(target=send, args=(s,), daemon=True).start()
        threading.Thread(target=onlineACK, args=(s,), daemon=True).start()
        threading.Thread(target=ai_worker, daemon=True).start() 

        ui = ChatUI()
        threading.Thread(target=write, args=(ui,), daemon=True).start()

        ui.start() 

        s.close()
        leave = True

    if __name__ == "__main__":
        main()
