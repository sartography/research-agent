
This is a testing ground for building a useful AI Agent that will do online research around our
core area of focus (the intersection of AI / BPMN / Python).  

## Dependencies
Right now this is using Anthropic and Kagi.  Kagi is a paid search engine with an API.
It's ok to alter this to allow using other AI agents.  Kagi is somewhat baked in, as we 
make use of it's lens filters, which are a happy thing.  

To get this running you will need:

1. a .env file that contains two secrets:  KAGI_KEY and ANTHROPIC_API_KEY
2. uv - our package manager, and the packages installed.

From there you can just ``uv run main.py``

This is a very simple project.  Take a look at config.py.  Particularly the second half, whree we configure
what general searches, RSS feeds and blogs we want to keep track of.  