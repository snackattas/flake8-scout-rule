# fmt: off
import os
import sys


def foo():
    print("Hello, world!")
    print("This is a line with trailing whitespace.    ")
    print("This line is too long and will cause a line length error because it exceeds the max allowed characters in a line of code")

def bar(x,y):
    if x>y:
        print("x is greater than y")
    else:
        print("x is not greater than y")

def qux(): a = 1; b = 2; print(a + b)

def check_none(value):
    if value == None:
        print("Value is None")

l = [1, 2, 3]
# fmt: on
