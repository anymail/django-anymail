from setuptools import setup
import re

# define __version__ and __minor_version__ from anymail/_version.py,
# but without importing from anymail (which would break setup)
__version__ = "UNSET"
__minor_version__ = "UNSET"
with open("anymail/_version.py") as f:
    code = compile(f.read(), "anymail/_version.py", 'exec')
    exec(code)


def long_description_from_readme(rst):
    # Freeze external links to refer to this X.Y version (on PyPI).
    # (This relies on tagging or branching releases with 'vX.Y' in GitHub.)
    release = 'v%s' % __minor_version__  # vX.Y
    rst = re.sub(r'(?<=branch=)master'     # Travis build status: branch=master --> branch=vX.Y
                 r'|(?<=/)latest'          # ReadTheDocs links: /latest --> /vX.Y
                 r'|(?<=version=)latest',  # ReadTheDocs badge: version=latest --> version=vX.Y
                 release, rst)  # (?<=...) is "positive lookbehind": must be there, but won't get replaced
    return rst

with open('README.rst') as f:
    long_description = long_description_from_readme(f.read())

setup(
    name="django-anymail",
    version=__version__,
    description='Django email backends for Mailgun, Postmark, SendGrid and other transactional ESPs',
    keywords="django, email, email backend, ESP, transactional mail, mailgun, mandrill, postmark, sendgrid",
    author="Mike Edmunds <medmunds@gmail.com>",
    author_email="medmunds@gmail.com",
    url="https://github.com/anymail/django-anymail",
    license="BSD License",
    packages=["anymail"],
    zip_safe=False,
    install_requires=["django>=1.8", "requests>=2.4.3", "six"],
    extras_require={
        # This can be used if particular backends have unique dependencies
        # (e.g., AWS-SES would want boto).
        # For simplicity, requests is included in the base requirements.
        "mailgun": [],
        "mandrill": [],
        "postmark": [],
        "sendgrid": [],
        "sparkpost": ["sparkpost"],
    },
    include_package_data=True,
    test_suite="runtests.runtests",
    tests_require=["mock", "sparkpost"],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Programming Language :: Python",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "License :: OSI Approved :: BSD License",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Framework :: Django",
        "Environment :: Web Environment",
    ],
    long_description=long_description,
)
