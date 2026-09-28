"""The machines' seat positions as measured on the real gym floor, pin number
as printed on the machine -> floor-to-seat height (mm).

Field visit 2026-09 (seat heights to the front of the seat). This file is
the record to update after each visit: if the code's axis definitions ever
drift from what's physically there — hole count, height, or which end is
pin 1 — this fails. Before it existed, Chest Press / Shoulder Press /
Seated Row all had their numbering mirrored (pin 1 = top in code, bottom on
the machine), and every pin the assistant gave for them was wrong.
"""

import pytest

from biomechanics import node_position, pin_label
from machines import chest_press, pec_deck, seated_row, shoulder_press

FIELD_SEAT_HEIGHTS_MM = {
    # Lowest position is marked 0; 1-5 above it.
    "chest_press": (chest_press.SEAT_AXIS, {0: 360, 1: 390, 2: 420, 3: 450, 4: 480, 5: 510}),
    "shoulder_press": (shoulder_press.SEAT_AXIS, {1: 350, 2: 380, 3: 410, 4: 440, 5: 470}),
    "seated_row": (seated_row.SEAT_AXIS, {1: 410, 2: 440, 3: 470, 4: 500, 5: 530, 6: 560}),
    # Numbered from the top. Two machines measured: 57..39 and 58..40 (the
    # second with uneven steps); the code follows the first, within 10mm of both.
    "pec_deck": (pec_deck.SEAT_AXIS, {1: 570, 2: 540, 3: 510, 4: 480, 5: 450, 6: 420, 7: 390}),
}


@pytest.mark.parametrize("machine", FIELD_SEAT_HEIGHTS_MM)
def test_seat_pins_match_the_machine(machine):
    axis, field = FIELD_SEAT_HEIGHTS_MM[machine]
    code = {pin_label(axis, n): node_position(axis, n) for n in range(1, axis.total_holes + 1)}
    assert code == pytest.approx(field), f"{machine}: code {code} != field {field}"
