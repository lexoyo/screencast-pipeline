"""Reading nvidia-smi. Every sample below is real output from this machine."""

from screencast.gpu import Memory, explain, parse_memory, parse_processes, shortfall

SMI = """+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.95.05              Driver Version: 580.95.05      CUDA Version: 13.0     |
|-----------------------------------------+------------------------+----------------------+
|   0  NVIDIA GeForce RTX 3050 ...    Off |   00000000:01:00.0  On |                  N/A |
| N/A   55C    P8              5W /   35W |      62MiB /   4096MiB |     15%      Default |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            4384      G   /usr/bin/gnome-shell                      412MiB |
|    0   N/A  N/A            9012    C+G   /usr/lib64/chromium-browser/chromium      803MiB |
+-----------------------------------------------------------------------------------------+
"""


def test_the_memory_line_is_read():
    mem = parse_memory("NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4096, 229, 3540")
    assert mem == Memory("NVIDIA GeForce RTX 3050 Ti Laptop GPU", 4096, 229, 3540)


def test_a_truncated_memory_line_is_not_a_crash():
    assert parse_memory("") is None
    assert parse_memory("some, garbage, here, x") is None


def test_graphics_clients_are_seen_not_only_compute_ones():
    # the whole point: --query-compute-apps returns nothing here, yet chromium holds 800 MB
    found = parse_processes(SMI)
    assert [(p.pid, p.kind, p.used_mb) for p in found] == [
        (4384, "G", 412),
        (9012, "C+G", 803),
    ]


def test_the_process_name_keeps_its_path_and_loses_the_padding():
    assert parse_processes(SMI)[0].name == "/usr/bin/gnome-shell"


def test_the_table_header_is_not_mistaken_for_a_process():
    assert all(p.pid > 0 for p in parse_processes(SMI))


def test_no_gpu_means_no_processes():
    assert parse_processes("") == []


def test_enough_free_vram_asks_nothing():
    assert shortfall(3400, Memory("card", 4096, 229, 3540)) == 0


def test_missing_vram_is_reported_as_the_gap():
    assert shortfall(3400, Memory("card", 4096, 1200, 2500)) == 900


def test_a_machine_without_a_gpu_never_blocks_the_run():
    # the pipeline must still run where there is no card to ask
    assert shortfall(3400, None) == 0


def test_the_message_names_what_to_close():
    text = explain(3400, "sonorita-cli", Memory("RTX 3050", 4096, 1300, 2400), parse_processes(SMI))
    assert "3400" in text and "2400" in text
    assert "chromium" in text
    assert "9012" in text


def test_nothing_worth_closing_means_no_empty_list():
    text = explain(3400, "sonorita-cli", Memory("RTX 3050", 4096, 62, 3707), [])
    assert "occupée par" not in text


def test_the_compositor_noise_is_not_listed_as_something_to_close():
    small = parse_processes(
        "|    0   N/A  N/A            4384      G   /usr/bin/gnome-shell            2MiB |"
    )
    text = explain(3400, "sonorita-cli", Memory("RTX 3050", 4096, 1300, 2400), small)
    assert "gnome-shell" not in text
