"""
vincenty.py - Vincenty's Direct and Indirect formulae

From https://github.com/guardiangeomatics/pyall/blob/master/geodetic.py
(Apache licensed)

Linked from https://gist.github.com/jtornero/9f3ddabc6a89f8292bb2
Broken link to http://wegener.mechanik.tu-darmstadt.de/GMT-Help/Archiv/att-8710/Geodetic_py

Vincenty's Direct formula:
 
Given the latitude and longitude of a point (latitude1, longitude1),
the geodetic azimuth (alpha1Tp2),
and the ellipsoidal distance in meters (s) to a second point,

calculate the latitude and longitude of
the second point (latitude2, longitude2) and the reverse azimuth (alpha21).

Vincenty's Indirect formula:

Given the latitude and longitude of two points, calculate the geodetic azimuth,
reverse azimuth, and ellipsoidal distance in meters from the first point to the
second.

Used for COGO (coordinate geometry) and map traverse.
"""

import math

def position_from_rangebearing(latitude1, longitude1, alpha1To2, s):
    """
    Returns the lat and long of projected point and reverse azimuth
    given a reference point and a distance and azimuth to project.
    lats, longs and azimuths are passed in decimal degrees
    Returns ( latitude2,  longitude2,  alpha2To1 ) as a tuple 
    """
    f = 1.0 / 298.257223563		# WGS84
    a = 6378137.0 			# meters

    piD4 = math.atan(1.0)
    two_pi = piD4 * 8.0

    latitude1  = latitude1  * piD4 / 45.0
    longitude1 = longitude1 * piD4 / 45.0
    alpha1To2  = alpha1To2  * piD4 / 45.0
    if alpha1To2 < 0.0:
        alpha1To2 = alpha1To2 + two_pi
    if alpha1To2 > two_pi:
        alpha1To2 = alpha1To2 - two_pi

    b = a * (1.0 - f)

    TanU1 = (1-f) * math.tan(latitude1)
    U1 = math.atan(TanU1)
    sigma1 = math.atan2(TanU1, math.cos(alpha1To2))
    Sinalpha = math.cos(U1) * math.sin(alpha1To2)
    cosalpha_sq = 1.0 - Sinalpha * Sinalpha

    u2 = cosalpha_sq * (a * a - b * b ) / (b * b)
    A = 1.0 + (u2 / 16384) * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = (u2 / 1024) * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))

    # Starting with the approximation
    sigma = (s / (b * A))

    last_sigma = 2.0 * sigma + 2.0	# something impossible

    # Iterate the following three equations 
    #  until there is no significant change in sigma 

    # two_sigma_m , delta_sigma
    while abs((last_sigma - sigma) / sigma) > 1.0e-9:
        two_sigma_m = 2 * sigma1 + sigma

        delta_sigma = B * math.sin(sigma) * ( math.cos(two_sigma_m) \
                        + (B/4) * (math.cos(sigma) * \
                        (-1 + 2 * math.pow( math.cos(two_sigma_m), 2 ) -  \
                        (B/6) * math.cos(two_sigma_m) * \
                        (-3 + 4 * math.pow(math.sin(sigma), 2 )) *  \
                        (-3 + 4 * math.pow( math.cos (two_sigma_m), 2 ))))) \

        last_sigma = sigma
        sigma = (s / (b * A)) + delta_sigma

    latitude2 = math.atan2 ( (math.sin(U1) * math.cos(sigma) + math.cos(U1) * math.sin(sigma) * math.cos(alpha1To2) ), \
                ((1-f) * math.sqrt( math.pow(Sinalpha, 2) +  \
                pow(math.sin(U1) * math.sin(sigma) - math.cos(U1) * math.cos(sigma) * math.cos(alpha1To2), 2))))

    lembda = math.atan2( (math.sin(sigma) * math.sin(alpha1To2 )), (math.cos(U1) * math.cos(sigma) -  \
                math.sin(U1) *  math.sin(sigma) * math.cos(alpha1To2)))

    C = (f/16) * cosalpha_sq * (4 + f * (4 - 3 * cosalpha_sq ))

    omega = lembda - (1-C) * f * Sinalpha *  \
                (sigma + C * math.sin(sigma) * (math.cos(two_sigma_m) + \
                C * math.cos(sigma) * (-1 + 2 * math.pow(math.cos(two_sigma_m),2) )))

    longitude2 = longitude1 + omega

    alpha21 = math.atan2 ( Sinalpha, (-math.sin(U1) * math.sin(sigma) +  \
                math.cos(U1) * math.cos(sigma) * math.cos(alpha1To2)))

    alpha21 = alpha21 + two_pi / 2.0
    if ( alpha21 < 0.0 ) :
        alpha21 = alpha21 + two_pi
    if ( alpha21 > two_pi ) :
        alpha21 = alpha21 - two_pi

    latitude2  = latitude2  * 45.0 / piD4
    longitude2 = longitude2 * 45.0 / piD4
    alpha21    = alpha21    * 45.0 / piD4

    return latitude2, longitude2, alpha21 


def rangebearing_from_positions(latitude1, longitude1,  latitude2,  longitude2):
    """ 
    Returns s, the distance between two geographic points on the ellipsoid
    and alpha1, alpha2, the forward and reverse azimuths between these points.
    lats, longs and azimuths are in decimal degrees, distance in metres 
    Returns ( s, alpha1Tp2,  alpha21 ) as a tuple
    """
    f = 1.0 / 298.257223563		# WGS84
    a = 6378137.0 			# metres

    if abs(latitude2 - latitude1) < 1e-8 and abs(longitude2 - longitude1) < 1e-8:
        return 0.0, 0.0, 0.0

    piD4   = math.atan( 1.0 )
    two_pi = piD4 * 8.0

    latitude1  = latitude1  * piD4 / 45.0
    longitude1 = longitude1 * piD4 / 45.0
    latitude2  = latitude2  * piD4 / 45.0
    longitude2 = longitude2 * piD4 / 45.0

    b = a * (1.0 - f)

    TanU1 = (1-f) * math.tan(latitude1)
    TanU2 = (1-f) * math.tan(latitude2)

    U1 = math.atan(TanU1)
    U2 = math.atan(TanU2)

    lembda = longitude2 - longitude1
    last_lembda = -4000000.0		# an impossible value
    omega = lembda

    # Iterate the following equations, 
    #  until there is no significant change in lembda 

    while last_lembda < -3000000.0 or lembda != 0 and abs((last_lembda - lembda)/lembda) > 1.0e-9:

        sqr_sin_sigma = pow( math.cos(U2) * math.sin(lembda), 2) + \
            pow( (math.cos(U1) * math.sin(U2) - \
                  math.sin(U1) *  math.cos(U2) * math.cos(lembda) ), 2 )

        Sin_sigma = math.sqrt( sqr_sin_sigma )

        Cos_sigma = math.sin(U1) * math.sin(U2) + math.cos(U1) * math.cos(U2) * math.cos(lembda)
        
        sigma = math.atan2( Sin_sigma, Cos_sigma )

        Sin_alpha = math.cos(U1) * math.cos(U2) * math.sin(lembda) / math.sin(sigma)
        alpha = math.asin( Sin_alpha )

        Cos2sigma_m = math.cos(sigma) - (2 * math.sin(U1) * math.sin(U2) / pow(math.cos(alpha), 2) )

        C = (f/16) * pow(math.cos(alpha), 2) * (4 + f * (4 - 3 * pow(math.cos(alpha), 2)))

        last_lembda = lembda

        lembda = omega + (1-C) * f * math.sin(alpha) * (sigma + C * math.sin(sigma) * \
               (Cos2sigma_m + C * math.cos(sigma) * (-1 + 2 * pow(Cos2sigma_m, 2) )))

    u2 = pow(math.cos(alpha),2) * (a*a-b*b) / (b*b)

    A = 1 + (u2/16384) * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))

    B = (u2/1024) * (256 + u2 * (-128+ u2 * (74 - 47 * u2)))

    delta_sigma = B * Sin_sigma * (Cos2sigma_m + (B/4) * \
                (Cos_sigma * (-1 + 2 * pow(Cos2sigma_m, 2) ) - \
                (B/6) * Cos2sigma_m * (-3 + 4 * sqr_sin_sigma) * \
                (-3 + 4 * pow(Cos2sigma_m,2 ) )))

    s = b * A * (sigma - delta_sigma)

    alpha1Tp2 = math.atan2( (math.cos(U2) * math.sin(lembda)), \
                (math.cos(U1) * math.sin(U2) - math.sin(U1) * math.cos(U2) * math.cos(lembda)))

    alpha21 = math.atan2( (math.cos(U1) * math.sin(lembda)), \
                (-math.sin(U1) * math.cos(U2) + math.cos(U1) * math.sin(U2) * math.cos(lembda)))

    if alpha1Tp2 < 0.0:
        alpha1Tp2 =  alpha1Tp2 + two_pi
    if alpha1Tp2 > two_pi:
        alpha1Tp2 = alpha1Tp2 - two_pi

    alpha21 = alpha21 + two_pi / 2.0
    if alpha21 < 0.0:
        alpha21 = alpha21 + two_pi
    if alpha21 > two_pi:
        alpha21 = alpha21 - two_pi

    alpha1Tp2 = alpha1Tp2  * 45.0 / piD4
    alpha21   = alpha21    * 45.0 / piD4
    return s, alpha1Tp2,  alpha21 
