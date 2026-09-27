"""编译器与运行器。"""
import sys
from syntax import Lexer, Parser, Interpreter, HeapvError


class Compiler:
    def __init__(self):
        self.interpreter = Interpreter()

    def compile(self, source: str):
        lexer = Lexer(source)
        lines = lexer.tokenize()
        parser = Parser(lines)
        return parser.parse()

    def run(self, source: str, out=None):
        if out is None:
            self.interpreter.run(self.compile(source))
            return
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = out
        try:
            self.interpreter.run(self.compile(source))
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
