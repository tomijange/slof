"""Network treatments that are planned but not implemented yet"""

from oxn.models.treatment import RuntimeTreatment


class PacketReorderTreatment(RuntimeTreatment):
    """
    Reorder packets. This can be used to simulate different cache locality effects.
    This is an example of a non-destructive treatment incompatible with the chaos engineering approach.
    Rather, this could be used to improve upon the system.
    Confer https://www.usenix.org/conference/nsdi22/presentation/ghasemirahni
    """

    # TODO: implement packet reordering


class SlotTreatment(RuntimeTreatment):
    """Defer the delivery of accumulated packets to within a slot.
    Each slot is configurable with a minimum delay, number of bytes delivered per slot and
    number of delivered packets per slot.

    This treatment can be used to simulate bursty traffic, i.e. network congestion effects.
    """

    # TODO: implement slot treatment
