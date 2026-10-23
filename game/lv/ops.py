# Opcodes shared by the pack compiler (tools/lvc.py) and the engine.
# Every condition and effect is 4 bytes: op, a, b, c. c is a signed byte.

# Card types
EVENT = 1      # fleet event: fires on its own, may auto-pick an option by role A's trait
BEAT = 2       # crew or relationship beat between bound crew members
DECISION = 3   # fleet vote; open for `duration` days
DILEMMA = 4    # private choice for role A's owner; open for `duration` days
RESCUE = 5     # opened by an effect; resolved by any single ballot, else the default
ENDING = 6     # checked in pack order on the last flight day

# Card flag bits
F_ONCE = 1
F_DUE = 2      # fires whenever eligible, before the random picks (callbacks)

# Conditions
C_FLAG = 1        # a = flag
C_NOFLAG = 2
C_VAR_GE = 3      # a = var, c = value
C_VAR_LE = 4
C_SINCE_GE = 5    # a = var holding a day (0 = never), b = days
C_RES_GE = 6      # a = resource, c = value (scaled: stored value is the real value)
C_RES_LE = 7
C_TRAIT_GE = 8    # a = role, b = axis, c = value
C_TRAIT_LE = 9
C_BOND_GE = 10    # a = role, b = role, c = value
C_BOND_LE = 11
C_SAME = 12       # a, b = roles on the same ship
C_APART = 13
C_COND = 14       # a = role, b = condition
C_IDLE_GE = 15    # a = role, b = days since its owner last acted
C_MORALE_LE = 16  # a = role, c = value
C_MORALE_GE = 17
C_FIRED = 18      # a = card
C_NOTFIRED = 19
C_KIT_ELSE = 20   # a = role: some other ship has a med kit
C_BESTBOND = 21   # a = role, b = role: a is b's strongest bond (ties: lowest index)
C_IS = 22         # a = role, b = var holding crew index + 1
C_DAY_GE = 23     # b = day
C_HOME = 24       # a = role is aboard its own ship
C_AWAY = 25

# Effects
E_SET = 1         # a = flag
E_CLR = 2
E_VADD = 3        # a = var, c = delta
E_MARK = 4        # a = var := today
E_RADD = 5        # a = resource, c = delta
E_TRAIT = 6       # a = role, b = axis, c = delta
E_BOND = 7        # a = role, b = role, c = delta
E_MORALE = 8      # a = role, c = delta
E_COND = 9        # a = role, b = condition
E_MOVE = 10       # a = role moves to role b's ship
E_KIT = 11        # a = role is treated with a kit from the best-stocked other ship
E_KITFROM = 12    # a = role brings a kit from its own ship to heal role b
E_OPEN = 13       # a = card (RESCUE/DECISION/DILEMMA) opens with the same roles
E_WHO = 14        # a = var := role b's crew index + 1
E_GOHOME = 15     # a = role returns to its own ship

COND_OK = 0
COND_INJURED = 1
COND_HOME = 2     # sent home on the supply capsule: out of the story, never dead

AXES = ("brave", "curious", "warm")     # negative ends: cautious, settled, prickly
RESOURCES = ("food", "fuel", "spares")
CONDITIONS = ("ok", "injured", "home")
ROLES = "ABCD"

NONE = 255

# Output entry codes (8 bytes each: day, code, card, a, b, c, d, e)
O_EVENT = 1       # card, A, B, option (255 = none)
O_DEC_OPEN = 2    # card, A, B
O_DEC_CLOSE = 3   # card, option, ballots, defaulted (1 = crew lean decided)
O_DIL_OPEN = 4    # card, A
O_DIL_CLOSE = 5   # card, A, option, by (0 = owner, 1 = astronaut in character)
O_ACT = 6         # crew, action, target, auto (1 = astronaut chose), param
O_MOVE = 7        # crew, from ship, to ship
O_NOTE = 8        # crew, line, target
O_END = 9         # card
O_RES_OPEN = 10   # card, A, B
O_RES_CLOSE = 11  # card, option, ballots, defaulted
O_SHORT = 12      # resource running low
