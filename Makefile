N_SIMS ?= 25000
ACTIVE_ONLY ?= 

run-bot:
	uv run python main.py run-bot

deploy:
	ssh rory@rory-Kratos 'cd ~/src/teleguessr && git stash && git checkout master && git pull && sudo systemctl restart teleguessr && echo "Deployed successfully!"'

sync-data:
	rm -rf data/ && mkdir data && scp -r rory@rory-Kratos:/home/rory/src/teleguessr/data/* ./data

predictions:
	uv run python main.py predictions -n $(N_SIMS) $(if $(ACTIVE_ONLY),--active-only)

resync-adjustments:
	scp -r ./data/adjustments rory@rory-Kratos:/home/rory/src/teleguessr/data/