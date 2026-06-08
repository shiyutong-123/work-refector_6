#shell.py

import contextlib
import sys
import os
import subprocess
import logging
import time
from functools import wraps
from typing import Optional, List, Dict, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.history import History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pygments.lexers import PythonLexer

from Core.interpreter import MyInteractiveInterpreter
from Core.magic_commands import MagicCommandHandler
from Core.utils import color_print, show_startup_info

# --- 配置与日志 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SinglePython")

class Config:
    INDENT = "    "
    PROMPT_STYLE = Style.from_dict({
        'pygments.keyword': 'bold #ff79c6',
        'pygments.operator': '#ff79c6',
        'pygments.punctuation': '#ff79c6',
        'pygments.name.function': '#50fa7b',
        'pygments.name.class': 'bold #50fa7b',
        'pygments.literal.string': '#f1fa8c',
        'pygments.literal.number': '#bd93f9',
        'pygments.comment': '#6272a4',
    })

def robust_run(func):
    """全局异常捕获与耗时记录装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
        finally:
            elapsed = time.time() - start_time
            if elapsed > 0.5:  # 仅记录耗时较长的操作
                logger.debug(f"{func.__name__} took {elapsed:.2f}s")
    return wrapper

# --- 核心 Shell 类 ---

class BlockAutoSuggestFromHistory(AutoSuggest):
    def get_suggestion(self, buffer, document) -> Optional[Suggestion]:
        history: History = buffer.history
        text = document.text
        if not text.strip():
            return None
        for entry in reversed(list(history.get_strings())):
            entry = entry.rstrip("\n")
            if entry.startswith(text) and entry != text:
                if suggestion := entry[len(text) :]:
                    return Suggestion(suggestion)
        return None

class SinglePythonShell:
    CURSOR_NONE, CURSOR_LINE, CURSOR_BLOCK, CURSOR_CIRCLE, CURSOR_UNDERLINE, CURSOR_BLINKING_LINE, CURSOR_BAR = range(7)

    @staticmethod
    def set_cursor_shape(shape: int):
        with contextlib.suppress(Exception):
            sys.stdout.write(f"\033[{shape} q")
            sys.stdout.flush()

    def __init__(self, version_info: Any = None):
        self.version_info = version_info
        self.multiline_comment = False
        self.buffered_code: List[str] = []
        self._indent_stack = [0]
        self.input_count = 1
        self.session = self.init_prompt_session()
        self.prompt_message = f"In [{self.input_count}]: "
        self.interpreter = MyInteractiveInterpreter()
        self.first_line_processed = False
        self.magic_command_handler = MagicCommandHandler(self)

    def init_prompt_session(self) -> PromptSession:
        self._history = InMemoryHistory()
        return PromptSession(
            lexer=PygmentsLexer(PythonLexer),
            auto_suggest=BlockAutoSuggestFromHistory(),
            history=self._history,
            key_bindings=self.get_key_bindings(),
            style=Config.PROMPT_STYLE,
            enable_history_search=True,
        )

    @staticmethod
    def get_key_bindings() -> KeyBindings:
        bindings = KeyBindings()
        @bindings.add(Keys.Tab)
        def _(event): event.app.current_buffer.insert_text(Config.INDENT)
        @bindings.add("c-c")
        def _(event): sys.exit(0)
        return bindings

    def reset_state(self):
        self.buffered_code.clear()
        self._indent_stack = [0]
        self.input_count += 1
        self.prompt_message = f"In [{self.input_count}]: "
        self.multiline_comment = False
        self.first_line_processed = False

    @robust_run
    def handle_user_input(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped: return False
        
        # 命令处理分发
        if stripped == "exit": sys.exit(0)
        if stripped in {"cls", "clear"}:
            subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
            self.reset_state()
            return True
        if stripped.startswith(("!", "%")):
            self.magic_command_handler.handle_magic_command(text) if stripped.startswith("%") else subprocess.run(stripped[1:], shell=True)
            self.reset_state()
            return True
        
        # 变量输出
        if stripped in self.interpreter.locals:
            print(f"Out[{self.input_count}]: {self.interpreter.locals[stripped]}\n")
            self.reset_state()
            return True

        self._update_indent_stack(text)
        self.buffered_code.append(text)
        return False

    def _update_indent_stack(self, text: str):
        stripped = text.strip()
        if not stripped or stripped.startswith('#'): return
        if stripped.endswith(':'):
            self._indent_stack.append(self._indent_stack[-1] + len(Config.INDENT))

    def run(self):
        if self.version_info: show_startup_info(self.version_info)
        while True:
            try:
                self.set_cursor_shape(self.CURSOR_BLINKING_LINE)
                prompt = "   ...:" if self.multiline_comment else self.prompt_message
                text = self.session.prompt(prompt)
                self.set_cursor_shape(self.CURSOR_BLOCK)

                if self.handle_user_input(text): continue
                
                # 执行代码
                compiled = compile("\n".join(self.buffered_code), "<input>", "exec")
                self.interpreter.runcode(compiled)
                self.reset_state()
            except KeyboardInterrupt:
                self.reset_state()
                print("\nKeyboardInterrupt")
            except EOFError:
                break