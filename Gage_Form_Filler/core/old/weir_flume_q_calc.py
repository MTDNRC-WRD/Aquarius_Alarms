import json
import pandas as pd
import math


def rectangular_suppressed(c, l, h):
    q = c * l * h**1.5
    return q


def rectangular_contracted(c, l, h):
    q = c * (l - (0.02 * h)) * h ** 1.5
    return q


def trapezoidal_weir(z, l, h):
    q = (3.33 * l * h**1.5) + 2 * ((2/5) * 3.367 * z * h**2.5)
    return q


def cipoletti_weir(l, h):
    q = 3.367 * l * h**(3 / 2)
    return q


def v_notch(h):
    q = 2.49 * math.tan(h/2)**2.48
    return q


def weir_calc(s_df):
    # this is the extracted csv of new data only

    for index, row in s_df.iterrows():
        if 'Weir' in row['Measurement Type']:
            if row['Weir Type'] is 'Rectangular':
                if row['Rectangular Weir Type'] is 'Suppressed':
                    if row['Crest Type'] is 'Broad Crested':
                        ans = rectangular_suppressed(3.33, row['Total Crest Length (ft)'], row['Water Depth (ft)'])
                    if row['Crest Type'] is 'Sharp Crested':
                        ans = rectangular_suppressed(3.1, row['Total Crest Length (ft)'], row['Water Depth (ft)'])
                if row['Rectangular Weir Type'] is 'Contracted':
                    if row['Crest Type'] is 'Broad Crested':
                        ans = rectangular_contracted(3.33, row['Total Crest Length (ft)'], row['Water Depth (ft)'])
                    if row['Crest Type'] is 'Sharp Crested':
                        ans = rectangular_contracted(3.1, row['Total Crest Length (ft)'], row['Water Depth (ft)'])

            if row['Weir Type'] is 'Trapezoidal':
                if float(row['Side Slope (L/h)']) is 0.25:
                    ans = cipoletti_weir(row['Total Crest Length (ft)'], row['Water Depth (ft)'])
                else:
                    ans = trapezoidal_weir(row['Side Slope (L/h)'], row['Total Crest Length (ft)'], row['Water Depth (ft)'])

            if row['Weir Type'] is 'V-Notch':
                ans = v_notch(row['Total Angle (deg)'])

            if row['Weir Type'] is 'Compound':

                if row['Upper Weir Type'] is 'Rectangular':
                    if row['Rectangular Weir Type'] is 'Suppressed':
                        if row['Crest Type'] is 'Broad Crested':
                            u_ans = rectangular_suppressed(3.33, row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])
                        if row['Crest Type'] is 'Sharp Crested':
                            u_ans = rectangular_suppressed(3.1, row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])
                    if row['Rectangular Weir Type'] is 'Contracted':
                        if row['Crest Type'] is 'Broad Crested':
                            u_ans = rectangular_contracted(3.33, row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])
                        if row['Crest Type'] is 'Sharp Crested':
                            u_ans = rectangular_contracted(3.1, row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])
                if row['Upper Weir Type'] is 'Trapezoidal':
                    if float(row['Upper Side Slope (L/h)']) is 0.25:
                        u_ans = cipoletti_weir(row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])
                    else:
                        u_ans = trapezoidal_weir(row['Upper Side Slope (L/h)'], row['Upper Crest Length (ft)'], row['Upper Water Depth (ft)'])

                if row['Lower Weir Type'] is 'Rectangular':
                    if row['Crest Type'] is 'Broad Crested':
                        l_ans = rectangular_contracted(3.33, row['Lower Crest Length (ft)'], row['Lower Water Depth (ft)'])
                    if row['Crest Type'] is 'Sharp Crested':
                        l_ans = rectangular_contracted(3.1, row['Lower Crest Length (ft)'], row['Lower Water Depth (ft)'])
                if row['Lower Weir Type'] is 'Trapezoidal':
                    if float(row['Lower Side Slope (L/h)']) is 0.25:
                        l_ans = cipoletti_weir(row['Lower Crest Length (ft)'], row['Lower Water Depth (ft)'])
                    else:
                        l_ans = trapezoidal_weir(row['Lower Side Slope (L/h)'], row['Lower Crest Length (ft)'], row['Lower Water Depth (ft)'])
                if row['Lower Weir Type'] is 'V-Notch':
                    l_ans = v_notch(row['Lower Total Angle (deg)'])
                ans = l_ans + u_ans
    return ans

# if 'Flume' in row['Measurement Type']:
#     pass






