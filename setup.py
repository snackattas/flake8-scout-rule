from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="flake8_scout_rule",
    license="MIT",
    version="1.0.0",
    description="""A Flake8 formatter that applies '# noqa: <errors>' annotations to flake8 violations found, helping to incrementally improve code quality.""",  # noqa: E501
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Zachary Attas",
    author_email="zach.attas@gmail.com",
    url="https://github.com/snackattas/flake8-scout-rule",
    packages=find_packages(),
    entry_points={
        "flake8.report": [
            "scout = flake8_scout_rule:Flake8ScoutRuleFormatter",
        ],
    },
    classifiers=[
        "Framework :: Flake8",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Quality Assurance",
    ],
    install_requires=["flake8>=3.8.0", 'importlib-metadata; python_version<"3.7"'],
    tests_require=[
        "black",
        "isort",
        "mypy",
        "pre-commit",
        "pytest",
    ],
)
