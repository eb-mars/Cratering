"""Cratering Functions."""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
import matplotlib
import mpl_toolkits.axes_grid1 as axtk
import os
import shutil
import sys
import yaml
import warnings
from packaging import version
import craterstats as cst
from landlab import RasterModelGrid
from landlab import imshow_grid
import math

seed = 3
rn_gen = np.random.default_rng(seed=seed);

def weights(minD, maxD):
    """ randomly generate a number and see which weight number in the input list it falls under,
    return the index of that weight 
    
    Parameters 
    ----------
    minD : int
        Minimum crater diameter, km

    maxD : int
        Maximum crater diameter, km
    
    Returns
    ----------
    i : weight
    """ 
    rn_gen = np.random.default_rng(seed=seed);
    
    ###  These parameters describe the population frequency for crater diameters:
    Kx = 1.0    #Scaling coefficient (Howard, 2007)
    delta = 2.0 #km, scaling exponent (Howard, 2007)
    
    weights = []
    for D in range(minD, maxD):
        w = Kx * D **-delta
        weights.append(w)

    rnd = rn_gen.random(1) * sum(weights)
    for i, ww in enumerate(weights):
        rnd -= ww
        if rnd < 0:
            return i

def make_noisy_surface(grid_size, cell_size, slope = 0, rf=1):
    ''' Generate a surface with random topography.
     Parameters
    ----------
    grid size : integer
        Size of the domain, in m 
        (note: domain is square so length = width)
    
    cell_size : integer
        Size of each cell in m.
        
    slope: int, float
        The slope (rise over run) to apply to the model grid (default = 0, i.e. flat surface).
    
    rf : int, float
        The multiplier (in m) to add to increase or decrease randomness by factor rf. 
        (randomness factor, default = 1, i.e. no extra scaling)
        
    Returns
    ----------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
    '''
    rn_gen = np.random.default_rng(seed=seed);
    
    xy = int(grid_size / cell_size) ## The number of cells along each axis of the domain (i.e. length in # cells)
    
    mg = RasterModelGrid((xy,xy), xy_spacing = cell_size); #initiate surface; see above for variables
    z = mg.add_zeros('topographic__elevation', at='node') #create an array of zeros for each node of the model grid  
    
    ## add slope
    z -= mg.node_x * slope/rf; #.node_x -> left-right slope, .node_y --> top-bottom slope, + vs. - changes direction of slope.

    # Add random elevation values at each node 
    z += rn_gen.random(mg.number_of_nodes);     
    mg.at_node["topographic__elevation"] *= rf  # make the noise large enough relative to crater

    return mg


def crater_depth(mg, d, diameter, rim = True):
    """
    Define changes to topography due to impact crater formation (including out of crater, i.e. ejecta addition) . 
    Note: This implementation is based on that of Howard (2007) and that MARSSIM model, (written in Fortran)

    Parameters
    ----------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
   
    d : np.ndarray 
        Array of distances of nodes to the center of the crater.
        In the same units as the grid (i.e. if grid is in meters, the units for d will be in meters)
        From `landlab.grid.raster.RasterModelGrid.calc_distances_of_nodes_to_point`
    
    diameter : int, float ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        Diameter of the crater (in km)
        
    rim : boolean, default = True
        whether the crater generated has a crater rim or not. 

    Returns
    -------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid after crater has modified the topography
    """
    ## Some Parameters to set
    rn_gen = np.random.default_rng(seed=seed); ## initialize the random number generator
    ejecta_noise = 0.05; ##ejecta noise standard deviation
    I = 1; ##inheritance parameter (between 0.5 to 1.0)
    
    diameter *= 1000; #convert input to meters
    radius = (diameter/2); #convert input to meters

    ## Check if it's simple or complex, and compute the shape parameters accordingly
    ## d_ref = 7 km on Mars (diameter for transition from simple to complex craters, where the shape changes!)
    if diameter <= 7000: #for a simple crater
        H1 = 2.54*diameter**0.67; #crater depth, in km
        H2 = 1.93*diameter**0.52; #max rim height, in km
        m = 0.73*(diameter)**0.11;  # value: 2 to 3, exponent for shape

    elif diameter > 7000: #for a complex crater
        H1 = 12.20*diameter**0.49; #crater depth, in km
        H2 = 0.79*diameter**0.6; #max rim height, in km
        m = 0.64*(diameter)**0.13;  # value: 2 to 3

    H2H1 = H2 - H1; #in km
    # Howard et al, 2007:
    # "The exponent n is constrained such that volume deposited on the rim
    # equals the volume excavated from the bowl and ranges from a value of
    # about 3 for a 7 km crater to 3.5 for a 250 km crater.""
    n = 2 - (H2 / ( (H2H1)/2 + H1/(m+2) )) ; ## crater exterior shape exponent;
    
    ## Calculate Noise:
    noise1 = ejecta_noise / (math.exp(1) * math.exp(1)-1.0)**0.5; ## from Tim's version of Howard (2007) MARSSIM fortran code 
    noise2 = ( 1.0 - 0.5*noise1 ) * noise1; ## from Tim's version of Howard (2007) MARSSIM fortran code 
    Z_noise =  rn_gen.lognormal(mean = 0, sigma = noise2);## from Tim's version of Howard (2007) MARSSIM fortran code 

    ## Add the shape to the model grid
    ## Note: same maths for each "if", but if the user sets rim = False, no rim topo is added! :)
    
    if rim == True: ## (DEFAULT) If the user wants the craters to have a rim
        in_idx = np.where(d <= radius)[0]; ## define the area inside the crater
        out_idx = np.where(d > radius)[0]; ## define the area outside the crater
        
        ## Reference Elevation
        Z_in = mg.at_node['topographic__elevation'][in_idx]; ## the Z array for topo in the crater
        Z_out = mg.at_node['topographic__elevation'][out_idx]; ## the Z array for topo outside the crater
        avgin = np.average(Z_in); # in meters, the average elevation inside the crater
        avgout = np.average(Z_out); # in meters, the average elevation outside the crater
        E_ref_in = Z_in;  ## The reference elevation inside the crater, is just the Z array (no calculations);
        E_ref_out = avgin + avgout*(d[out_idx] / radius)**-n; #The reference elevation outside the crater is an equation (Howard, 2007)
        
        # Equations for inside the crater
        DH_in = H2H1 + Z_noise*H1*(  (2*d[in_idx])/diameter  )**m; #in meters, calculate the array of Z describing the shape of the crater
        DE_in = DH_in + 1*(E_ref_in - Z_in)*(1 - I*(d[in_idx]/radius)**2); ## calculate the array of Z values to add (accounting for inheritance & noise)
        mg.at_node['topographic__elevation'][in_idx] += DE_in; #add the Z
    
        ## equations for outside the crater   
        DH_out = H2*(  (2*d[out_idx])/diameter  )**-n; # in meters; calculate the array of Z values to add
        G = []; #initialize array for parameter G at each node
        for i in np.arange(0, len(out_idx), 1):
            Gi = np.min( [(1 - I), (DH_out[i]/H2)] );
            G.append(Gi);
        DE_out = DH_out + G*(E_ref_out - Z_out);
        mg.at_node['topographic__elevation'][out_idx] += DE_out; ## add the Z
    
    elif rim == False: ## If the user doesn't want the crater to have any rims
        in_idx = np.where(d <= radius * 0.9)[0] #Only excavate the crater for the first 90% of the crater radius
        ##90% of the crater radius ensures there's no rim on the crater for craters up to about 500 km in diameter
        ## For much smaller craters (< 250 km), a larger value than 90% could be used, but it still makes a reasonable crater
        out_idx = np.where(d > radius*0.9)[0]; ## define the area outside the crater
        
        ## Reference Elevation
        Z_in = mg.at_node['topographic__elevation'][in_idx];
        avgin = np.average(Z_in); # in meters
        E_ref_in = Z_in; ## divide by the "weight" at some point?
        
        # equations for inside the crater
        # ## MY TRANSLATION OF TIMS CODE: DH_in = (H2 - H1) + Z_noise*H1*( (d[in_idx]/radius)**m    ); ## is this missing a x2 in the numerator????
        DH_in = H2H1 + H1*(  (2*d[in_idx])/diameter  )**m; #in meters, calculate the array of Z describing the shape of the crater
        DE_in = DH_in + 1*(E_ref_in - Z_in)*(1 - I*(d[in_idx]/radius)**2); ## calculate the array of Z values to add (accounting for inheritance & noise)
        mg.at_node['topographic__elevation'][in_idx] += DE_in; #add the Z
    
        ## equations for outside the crater   
        mg.at_node['topographic__elevation'][out_idx] += 0; ## add the Z
        
        ## No Z is added outside the crater, to avoid adding a rim! :) (and if the rim is eroded, can assume the ejecta is pretty eroded/neglible as well).
     
    return mg



## for crater_production_function_inverese and generate_csfd_from_production_function
## load and format paths for craterstats functions
functions_path = os.path.join(cst.PATH, "config/functions.txt")
craterstats_functions = cst.gm.read_textstructure(functions_path)

def crater_production_function_inverse(pf, irange, y, tol=1e-6):
    """Inverse of the crater production function.
    This function is modified from Andrew Moodie's "CraterModel" code

    Parameters
    ----------
    pf :
        Production function

    irange
        Range of interest
        
    y : ?
        ?
    
    tol : ?
        ?
        
    Returns
    ----------
    ? : ?
        ?
    """
    log_y = np.log10(y)
    ## xrange = np.log10(pf.range)
    xrange = np.log10(irange)
    divisions = 9
    count = 0

    while True:
        x0 = np.linspace(xrange[1], xrange[0], divisions)  # reverse order because np.interp() requires increasing 'x-values'
        y0 = np.log10(pf.evaluate("cumulative", 10.0**x0))
        x = np.interp(log_y, y0, x0)
        y1 = np.log10(pf.evaluate("cumulative", 10.0**x))
        q = np.searchsorted(y0, log_y)

        xrange = x0[[q, q - 1]]
        count += 1
        if abs(y1 - log_y) < tol or count > 99:
            break

    return 10**x


def generate_CSFD_from_production_function(
    time_interval,
    size_interval,
    domain_area,
    cell_size,
    poisson_intervals=True):
    """
    Generate a Crater Size Frequency Distribution (CSFD) using Poisson space events.
    This function is modified from Andrew Moodie's "CraterModel" code

    Parameters
    ----------
    time_interval 
        2-element list of start time and end time in Ga (billion years ago), e.g. [4.5, 3.0]

    size_interval ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        2-element list of smallest and largest diameter craters to generate in km.

    domain_area : int ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        domain area in km2.
        
    cell_size : int ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        size of 1 cell, in km

    poisson_intervals
        Use Poisson spaced events (otherwise just expectation interval).
        
    Returns
    ---------
    list_d : list
        list of crater diameters generated in the specified time interval, for the specified domain area size.
        units are kilometers
    """
    rn_gen = np.random.default_rng(seed=seed);

    # production and chronology functions from "craterstats"
    production_function = cst.Productionfn(craterstats_functions, "Mars, Ivanov (2001)")
    chronology_function = cst.Chronologyfn(craterstats_functions, "Mars, Hartmann & Neukum (2001)")

    Area = domain_area  # modelled area in km2
    poisson_intervals = poisson_intervals  #

    list_d = []  # initiate a list for the diameters
    ## list_dt = []  # list of interarrival times

    diameter_range = size_interval  # in km
    
    if diameter_range == None:
        diameter_range = [cell_size, production_function.range[1]]; 
        # if no diameter range was input, the diameter range is from the cell size (smallest) 
        # to whatever the largest given by the producton function is (largest), i.e. what the production function was calibrated over
        # production_function.range[0] is 10s of m (10 - 50 m depending on the model used), which is probably much smaller than cell size for my models
    
    else: 
        if (diameter_range[0] < production_function.range[0]) or (diameter_range[1] > production_function.range[1]):
            warnings.warn("Crater range of interest was outside of production functions's defined range. Extrapolating.") 

    N = production_function.evaluate("cumulative", [1.0, diameter_range[0], diameter_range[1]])  # default a0
    N1_ratio = N[1] / N[0]

    t = time_interval[1]
    i = 0


    while t <= time_interval[0]:
        # generate crater diameter
        u = rn_gen.uniform(0, 1);
        y = u * (N[1] - N[2]) + N[2]
        d = crater_production_function_inverse(production_function, diameter_range, y)

        # time interval
        phi = chronology_function.phi(t)
        lam = phi * N1_ratio * Area
        if poisson_intervals:
            u = rn_gen.uniform(0, 1);
            dt = -np.log(u) / lam  # proper poisson interval
        else:
            dt = 1.0 / lam  # mean interval

        list_d.append(d)
        # list_dt.append(dt)

        t += dt
        i += 1

    return list_d


def add_craters1(mg, Ncraters, minD, maxD, rim = True):
    """
    Add craters to some landlab raster model, using functions "weights" and "crater_depth" 
    NOTE: The function "add_craters2" is a method which adds a more realistic ditribution of craters
    ("add_craters2" uses functions created by Andrew Moodie which draw diameters from a CSFD).

    Parameters
    ----------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
        
    Ncraters : int
        Number of craters that impact

    minD : int
        Minimum crater diameter, km

    maxD : int
        Maximum crater diameter, km
        
    rim : boolean, default = True
        whether the crater generated has a crater rim or not. 

    Returns
    -------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid after craters have modified the topography

    """
    rn_gen = np.random.default_rng(seed=seed); ## create an instance of the Generator class
    xy = mg.number_of_node_columns; #number of cells/nodes
    cell_size = mg.dx; #size of 1 cell, m (grid units)
    grid_size = int(cell_size * xy); #length of grid, m (grid units)
    
    print('   ---> not using CSFD...');
    print('   ---> adding {} craters...'.format(Ncraters));
    for i in range(Ncraters):  # For N number of craters
        a = weights(minD, maxD);
        diameter = list(range(minD, maxD))[a]
        cratercenter = (rn_gen.integers(1, grid_size, endpoint=True), rn_gen.integers(1, grid_size, endpoint = True))
        d = mg.calc_distances_of_nodes_to_point(cratercenter)

        crater_depth(mg, d, diameter, rim = rim)

    return mg

def add_craters2(mg, time_interval, size_interval, poisson_intervals=True, rim = True):
    """
    Add craters to a pre-defined landlab raster grid model.
    'add_craters2' USES TWO FUNCTIONS CREATED BY ANDREW MOODIE BASED ON CSFDs and "craterstats": 
    i.e., the functions "generate_CSFD_from_production_function" and "crater_production_function_inverse" (see above)
    
    The old function, 'add_craters1' uses functions written by Emily Bamber, 
    and produces a crater population that's less realistic
    
    Parameters
    ----------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
    
    time_interval : 2-element list
        2-element list of start time and end time in Ga.

    size_interval : 2-element list ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        2-element list of smallest and largest diameter craters to generate in km.

    domain_area ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        domain area in km2.

    poisson_intervals
        Use Poisson spaced events? (otherwise just expectation interval).
        
    rim : boolean, default = True
        whether the crater generated has a crater rim or not.
        argument to be passed to function "crater_depth"
        
    Returns
    -------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid after craters have modified the topography

    """
    rn_gen = np.random.default_rng(seed=seed);
    
    ## Get properties (size) of the grid
    xy = mg.number_of_node_columns; #number of cells/nodes
    cell_size = mg.dx/1000; #size of 1 cell, km, (grid units = m, so /1000 to get km)
    grid_size = int(cell_size * xy); #length of grid, km (grid units = m, so /1000 to get km)
    domain_area = grid_size * grid_size; ## km2
    
    print('   ---> generating CSFD...');
    diameter_list = generate_CSFD_from_production_function(time_interval, size_interval, domain_area, cell_size,
                                                           poisson_intervals=poisson_intervals);
    
    Ncraters = len(diameter_list);
    print('   ---> adding {} craters...'.format(Ncraters));
    for i in range(Ncraters):  # For N number of craters
        diameter = diameter_list[i]; #select the diameter
        cratercenter = (rn_gen.integers(1, grid_size*1000, endpoint = True), rn_gen.integers(1, grid_size*1000, endpoint = True));
        d = mg.calc_distances_of_nodes_to_point(cratercenter); #print(d)
        
        crater_depth(mg, d, diameter, rim = rim); 
    
    return mg


def central_crater(mg, diameter, rim = True):
    """
    Add a central crater to a Landlab raster model grid
    Parameters
    ----------
    mg : Landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
    
    diameter: int ** IMPORTANT THAT IT IS INPUT IN KILOMETERS NOT METERS ***
        Diameter of crater to be added at the central node, in km
    
    rim : boolean, default = True
        whether or not the central crater has a rim (True) or no rim (False). 
        This argument is passed to the function crater_depth
    
    Returns
    -------
    mg : landlab.grid.raster.RasterModelGrid
        Landlab raster model grid after a central crater has modified the topography
    """
    #### Get properties (size) of the grid
    xy = mg.number_of_node_columns; #number of cells/nodes 
    cell_size = mg.dx; #size of 1 cell, km, (grid units = m, so /1000 to get km)
    grid_size = int(cell_size * xy); #length of grid, km (grid units = m, so /1000 to get km)
    ### xy = int( grid_size / cell_size);
    
    d = mg.calc_distances_of_nodes_to_point( (int((grid_size)/2), int((grid_size)/2)) );
    
    crater_depth(mg, d, diameter, rim = rim);
    
    return(mg)

def plot_topo_profile(mg, grid_size, cell_size, Title = 'Title'):
    """
    Parameters
	----------
	mg : Landlab.grid.raster.RasterModelGrid
	Landlab raster model grid of the landscape
    
    grid size : integer
        Size of the domain, in m 
        (note: domain is square so length = width)
    
    cell_size : integer
        Size of each cell in m.
        
    Title : string
    title to add to the plot
    
    Returns
    ---------
    Plot of profile from left to right across the whole model grid width
    (through the center of the grid).
    
    """
    xy = int(grid_size / cell_size);
    y = mg.field_values('node', 'topographic__elevation').reshape((xy, xy))[int(xy/2)]; #reshape the topography so it's easy to find the midpoint row (index = xy/2)
    x = np.arange(xy)*cell_size; #create the x values (from 1 to xy)
    plt.plot(x, y, 'k-'); #create the plot, with a black line for topography
    plt.title(Title); #add a title
    plt.xlabel("X [m]"); plt.ylabel("Elevation [m]") #add x and y axis labels
    plt.show() #display the figure
    

def plot_grid(mg, grid_size, cell_size, Title='Title'):
    """
    Parameters
    ----------
    mg : Landlab.grid.raster.RasterModelGrid
        Landlab raster model grid of the landscape
     
           grid size : integer
        Size of the domain, in km 
        (note: domain is square so length = width)
    
    cell_size : integer
        Size of each cell in km.
    
    Title: string
        the title for the plot

    Returns
    -------
    None.

    """
    xy = int(grid_size / cell_size);
    
    cmap2 = mpl.cm.get_cmap("Spectral_r"); #define colour scheme for the topography
    cmap1 = mpl.cm.get_cmap("Greys_r"); #define colour scheme for the hillshade
    
    hs = mg.calc_hillshade_at_node(elevs='topographic__elevation') #create hillshade file
    topo = mg.field_values('node', 'topographic__elevation').reshape((xy, xy)) #reshape the topography to the right (square) shape for display
    hill = np.reshape(hs, (xy, xy)); #reshape the hillshade to the right (square) shape for display

    fig, ax = plt.subplots() #initiate figure
    img1 = plt.imshow(hill, cmap=cmap1, alpha=1, extent = [0,grid_size, 0, grid_size]) #plot hillshade
    img2 = plt.imshow(topo, cmap=cmap2, alpha=0.6, extent = [0,grid_size, 0, grid_size]) #plot topograpy
    fig.colorbar(img2,ax=ax, label="Elevation [m]") #add & label the colorbar
    plt.title(Title); #add a title
    plt.xlabel("X [m]"); plt.ylabel("Y [m]") #add x and y axis labels
    plt.show() #show the figure
    
    
    
