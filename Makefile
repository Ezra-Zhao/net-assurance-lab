.PHONY: run test clean
run:
	./run_lab.sh
test:
	python3 -m unittest discover -s tests -v
clean:
	rm -rf results/*
