"""
Hall-effect arithmetic.

Every formula here is carried over unchanged from Hall_v4.ipynb - only
relocated into its own module so it can be unit-tested without dragging
in Tkinter, the same way vdp_math.py was.

The measurement, in one paragraph: pass a known current through one
diagonal of the sample and sense the voltage across the other, in a
magnetic field. The Lorentz force pushes carriers sideways, so a small
transverse voltage appears on top of the ordinary resistive drop. That
resistive part is what the eight-term average removes.

Naming, which is easy to misread:
    V13, V31, V24, V42   - the four contact pairings. Swapping the digits
                           means the *current* was reversed.
    ...,P / ...,N        - the sign of the *magnetic field*, not current.

So V13,P and V31,P are the same field, opposite currents; V13,P and
V13,N are the same current, opposite fields.
"""

# CODATA elementary charge, as in the original.
Q_E = 1.602176634e-19


def hall_voltage(v13p, v31p, v24p, v42p, v13n, v31n, v24n, v42n):
    """The eight-measurement Hall voltage average.

        V_H = (V13P - V13N - V31P + V31N + V24P - V24N - V42P + V42N) / 8

    Why eight terms rather than one: the raw voltage across a contact
    pair is dominated by the ordinary resistive drop, plus thermoelectric
    and misalignment offsets, all of which are far larger than the Hall
    signal. Those unwanted terms keep their sign when the field or the
    current reverses; the Hall term flips. Summing with these signs
    cancels the offsets and keeps eight copies of the Hall term.

    Returns volts. The *sign* is meaningful - it indicates carrier type -
    so it is deliberately not made absolute here.
    """
    return (v13p - v13n - v31p + v31n + v24p - v24n - v42p + v42n) / 8.0


def sheet_carrier_density(current_a, field_t, hall_voltage_v):
    """Sheet carrier density in cm^-2.

        n_s = I * B / (q * V_H)

    computed in SI (giving m^-2) and multiplied by 1e-4 to reach cm^-2,
    which is how the original did it.

    Carries the sign of V_H through, so a negative result indicates the
    opposite carrier type rather than an error. Raises ZeroDivisionError
    on V_H = 0, which the caller reports as a dialog.
    """
    if hall_voltage_v == 0:
        raise ZeroDivisionError("V_H is zero - cannot compute carrier density")
    return (current_a * field_t) * 1e-4 / (Q_E * hall_voltage_v)


def hall_mobility(sheet_density_cm2, sheet_resistance):
    """Hall mobility in cm^2/(V*s).

        mu = 1 / (q * n_s * R_s)

    Note this same expression is correct for a bulk sample too, which is
    why the original used it for both. Substituting the bulk quantities,
    n_3D = n_s / t and rho = R_s * t, the thickness cancels:

        1 / (q * (n_s/t) * (R_s*t)) = 1 / (q * n_s * R_s)

    So there is deliberately no separate bulk mobility function.
    """
    if sheet_density_cm2 == 0 or sheet_resistance == 0:
        raise ZeroDivisionError("Cannot compute mobility from zero n_s or R_s")
    return 1.0 / (Q_E * sheet_density_cm2 * sheet_resistance)


def bulk_carrier_density(sheet_density_cm2, thickness_cm):
    """Volume carrier density in cm^-3, from the sheet density.

        n_3D = n_s / t

    Sheet density counts carriers per unit area of film; dividing by the
    film thickness spreads that count through the volume.
    """
    if thickness_cm <= 0:
        raise ValueError("Thickness must be positive")
    return sheet_density_cm2 / thickness_cm


def resistivity(sheet_resistance, thickness_cm):
    """Resistivity in ohm*cm.

        rho = R_s * t
    """
    if thickness_cm <= 0:
        raise ValueError("Thickness must be positive")
    return sheet_resistance * thickness_cm


def um_to_cm(thickness_um):
    """Thickness in micrometres to centimetres. One line, but it is the
    conversion most easily got wrong by a factor of 10000."""
    return thickness_um * 1e-4


# Carrier type labels, kept as constants so the UI and the tests agree.
N_TYPE = "n-type (electrons)"
P_TYPE = "p-type (holes)"
INDETERMINATE = "indeterminate"


def carrier_type(hall_voltage_v):
    """Infer the majority carrier type from the sign of V_H.

    The physics: the Lorentz force pushes *whatever is moving* to one
    side of the sample. Electrons and holes travel in opposite directions
    for the same conventional current, so they pile up on opposite edges
    and the transverse voltage comes out with opposite signs. The
    magnitude gives you how many carriers there are; the sign gives you
    which kind.

    With n_s computed as I*B/(q*V_H) using a positive elementary charge:

        V_H > 0  ->  n_s positive  ->  holes      ->  p-type
        V_H < 0  ->  n_s negative  ->  electrons  ->  n-type

    IMPORTANT - this is only as trustworthy as the wiring.

    The mapping above assumes the measurement geometry matches the one
    the formula was written for: a particular assignment of contacts 1-4,
    a particular direction of B relative to the sample face, and a
    particular current polarity. Reverse any *one* of those three at the
    switch box, the magnet, or the sample mount and the sign flips - so
    the reported type flips with it, while every magnitude stays right.

    Nothing in software can detect that, because a p-type sample wired
    backwards and an n-type sample wired correctly produce identical
    numbers. The fix is a one-off bench calibration: measure a sample of
    known type, and if the answer comes out inverted, correct the wiring
    (or the contact numbering) once and it stays correct.

    Returns one of N_TYPE, P_TYPE, or INDETERMINATE.
    """
    if hall_voltage_v > 0:
        return P_TYPE
    if hall_voltage_v < 0:
        return N_TYPE
    return INDETERMINATE
