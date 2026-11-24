from dataclasses import dataclass


@dataclass(frozen=True)
class DriveUnit:
    channel: str
    unit: str


def validate_drive_units(units):
    if not isinstance(units, (tuple, list)) or not units:
        raise ValueError('at least one drive channel is required')
    declarations = []
    names = set()
    for entry in units:
        if isinstance(entry, DriveUnit):
            channel, unit = entry.channel, entry.unit
        elif isinstance(entry, (tuple, list)) and len(entry) == 2:
            channel, unit = entry
        else:
            raise ValueError('expected a drive channel and unit pair')
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError('drive channel must be nonblank text')
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError('drive unit must be nonblank text')
        if channel in names:
            raise ValueError(f'duplicate drive channel: {channel}')
        names.add(channel)
        declarations.append(DriveUnit(channel, unit))
    return tuple(declarations)


def check_drive_units(declared, supplied):
    if set(declared) != set(validate_drive_units(supplied)):
        raise ValueError('drive channels or units do not match the schedule')
