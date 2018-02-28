from pkg_resources import get_distribution, DistributionNotFound

try:
    __version__ = get_distribution('gluetool').version

except DistributionNotFound:
    pass
