# STDLIB
import configparser
import copy

# LOCAL
from . import spectools


class ConstraintParser:

    def __init__(self, expr, linefit=None):

        self.linefit = linefit
        self.expr = expr
        self._operators = '+-*/><'
        self._containers = '()[]{}'
        self._spacer = ' \t\n\r'

        self.__limits__()
        self.__classify__()
        self._getConstraintType()

    @staticmethod
    def isnumber(s):

        try:
            float(s)
            return True
        except ValueError:
            return False

    def __what__(self, c):

        if c.isalpha():
            group = 'alpha'
        elif c.isdecimal() or (c == '.'):
            group = 'number'
        elif c in self._operators:
            group = 'operator'
        elif c in self._spacer:
            group = 'spacer'
        else:
            group = 'unkonwn'

        return group

    def __limits__(self):

        previous = ''
        lim = []

        for i, c in enumerate(self.expr):

            current = self.__what__(c)
            if current != previous:
                lim += [i]
                previous = copy.copy(current)
            else:
                continue

        self.lim = lim

    def __classify__(self):

        operators = []
        variables = []
        containers = []
        numbers = []

        for c in self.expr.split(' '):

            if any([i.isalpha() for i in c]):
                variables += [c]
            elif self.isnumber(c):
                numbers += [c]
            elif self.__what__(c) == 'operator':
                operators += [c]
            elif self.__what__(c) == 'container':
                containers += [c]
            elif self.__what__(c) == 'unknown':
                continue

        self.numbers = numbers
        self.operators = operators
        self.variables = variables
        self.containers = containers

    def __idx__(self, cname, pname):

        ci = self.linefit.component_names.index(cname)
        pi = self.linefit.par_names.index(pname)
        npars = len(self.linefit.par_names)

        idx = ci * npars + pi

        return idx

    def _getConstraintType(self):

        lis = self.tolist()

        if lis[0] in '<>':
            t = 'ineq'
        else:
            t = 'eq'

        self.type = t

    def evaluate(self, component, parameter):

        idx = self.__idx__(component, parameter)

        lis = self.tolist()

        if lis[0] == '<':
            lis.remove(lis[0])
            sign = 1.
        elif lis[0] == '>':
            lis.remove(lis[0])
            sign = -1.
        else:
            sign = 1.

        if len(lis) == 1:

            if (lis[0] in self.numbers):
                a = float(lis[0])

                def func(x):
                    r = sign * (a - x[idx])
                    return r

            elif (lis[0] in self.variables):
                idx2 = self.__idx__(lis[0], parameter)

                def func(x):
                    r = sign * (x[idx2] - x[idx])
                    return r

        elif len(lis) == 3:

            num = [i for i in lis if i in self.numbers][0]
            var = [i for i in lis if i in self.variables][0]
            idx2 = self.__idx__(var, parameter)
            a = float(num)
            oper = lis[1]

            if lis.index(num) > lis.index(var):
                if oper == '+':
                    def op(x, j):
                        return x[j] + a
                elif oper == '-':
                    def op(x, j):
                        return x[j] - a
                elif oper == '/':
                    def op(x, j):
                        return x[j] / a
                elif oper == '*':
                    def op(x, j):
                        return x[j] * a
            else:
                if oper == '+':
                    def op(x, j):
                        return a + x[j]
                elif oper == '-':
                    def op(x, j):
                        return a - x[j]
                elif oper == '/':
                    def op(x, j):
                        return a / x[j]
                elif oper == '*':
                    def op(x, j):
                        return a * x[j]

            def func(x):
                r = sign * (op(x, idx2) - x[idx])
                return r

        self.constraint = dict(type=self.type, fun=func)

    def tolist(self):

        elements = []
        lims = self.lim

        for i, j in enumerate(lims):

            if j == lims[-1]:
                c = self.expr[lims[i]:None]
            else:
                c = self.expr[lims[i]:lims[i + 1]]

            if c not in self._spacer:
                elements += [c]

        # return elements
        elements = self.expr.split(' ')
        elements = [i for i in elements if i != '']
        return elements


class LineFitParser:

    def __init__(self, *args, **kwargs):

        self.component_names = []
        self.p0 = []
        self.bounds = []
        self.constraints = []
        self.k_groups = []
        self.k_component_names = []
        self.cwin = {}

        if args or kwargs:
            self.__load__(*args, **kwargs)

    def __load__(self, fname, **kwargs):

        self.cfg = configparser.ConfigParser()
        self.cfg.read(fname)

        par_names = dict(
            gaussian=('flux', 'wavelength', 'sigma'),
            gausshermite=('flux', 'wavelength', 'sigma', 'h3', 'h4'),
        )

        self.par_names = par_names[
            self.cfg.get('fit', 'function', fallback='gaussian')]
        self.component_names = [
            i for i in self.cfg.sections() if i not in [
                'continuum', 'minimization', 'fit', 'equivalent_width']]

        # Each section has to be a line, except for the DEFAULT, MINOPTS,
        # and CONTINUUM sections, and equivalent_width.
        for line in self.component_names:
            self.parse_line(line)

        for line in self.component_names:
            for par in self.par_names:
                prop = self.cfg[line][par].split(',')
                self._constraints(prop, line, par)

        self._kinematic_constraints()
        self._fit()
        self._minimization()
        self._continuum()
        self._eqw()

    def __idx__(self, cname, pname):

        ci = self.component_names.index(cname)
        pi = self.par_names.index(pname)
        npars = len(self.par_names)

        idx = ci * npars + pi

        return idx

    def _parse_dict(self, section, float_args=(), int_args=(), bool_args=()):

        d = {**self.cfg[section]}

        for i in float_args:
            if i in d:
                d[i] = self.cfg.getfloat(section, i)

        for i in int_args:
            if i in d:
                d[i] = self.cfg.getint(section, i)

        for i in bool_args:
            if i in d:
                d[i] = self.cfg.getboolean(section, i)

        return d

    def _minimization(self):

        if 'minimization' in self.cfg.sections():
            self.minopts = self._parse_dict(
                section='minimization',
                float_args=['eps', 'ftol'],
                int_args=['maxiter'],
                bool_args=['disp'],
            )
        else:
            self.minopts = {}

    def _fit(self):

        if 'fit' not in self.cfg.sections():
            self.fit_opts = {}
            return

        fit_opts = {**self.cfg['fit']}
        string_values = ['peak', 'cofm']

        key = 'individual_spec'
        if key in fit_opts:
            if fit_opts[key] in string_values:
                pass
            else:
                try:
                    fit_opts[key] = self.cfg.getboolean('fit', key)
                    assert fit_opts[key] is not True,\
                        '*individual_spec* must be "peak", "no" or a pair of'\
                        ' spaxel coordinates "x, y".'
                except ValueError:
                    fit_opts[key] = tuple(
                        [int(i) for i in fit_opts[key].split(',')])

        key = 'spiral_center'
        if key in fit_opts:
            if fit_opts[key] in string_values:
                pass
            else:
                fit_opts[key] = tuple(
                    [int(i) for i in fit_opts[key].split(',')])

        boolean_args = [
            'writefits', 'refit', 'update_bounds', 'spiral_loop', 'verbose',
            'fit_continuum']
        for i in boolean_args:
            if i in fit_opts:
                fit_opts[i] = self.cfg.getboolean('fit', i)

        float_args = [
            'refit_radius', 'sig_threshold', 'inst_disp']
        for i in float_args:
            if i in fit_opts:
                fit_opts[i] = self.cfg.getfloat('fit', i)

        key = 'fitting_window'
        if key in fit_opts:
            a = fit_opts[key].split(':')
            fit_opts['fitting_window'] = tuple([float(i) for i in a])

        self.fit_opts = fit_opts

    def _eqw(self):

        if 'equivalent_width' in self.cfg.sections():
            self.eqw_opts = self._parse_dict(
                section='equivalent_width',
                float_args=('sigma_factor',))
        else:
            self.eqw_opts = {}

        self.eqw_opts['continuum_windows'] = self.cwin

    def _continuum(self):

        if 'continuum' in self.cfg.sections():
            self.copts = self._parse_dict(
                section='continuum',
                float_args=['lower_threshold', 'upper_threshold'],
                int_args=['degr', 'niterate'],
                bool_args=[],
            )
        else:
            self.copts = {}

    def _continuumWindows(self, line, line_pars):

        if 'continuum_windows' in line_pars:
            self.cwin[line] = [
                float(i) for i in
                line_pars.get('continuum_windows').split(',')]
        else:
            self.cwin[line] = None

    def _bounds(self, props):

        if len(props) > 1:
            if (~props[1].isspace()) and (props[1] != ''):
                if '+-' in props[1]:
                    number = float(props[1].split()[-1])
                    low, up = [float(props[0]) + i for i in [-number, +number]]
                elif ':' in props[1]:
                    low, up = [
                        float(i) if (i != '') else None
                        for i in props[1].split(':')]
                self.bounds += [(low, up)]
            else:
                self.bounds += [(None, None)]
        else:
            self.bounds += [(None, None)]

    def _constraints(self, props, component_name, par_name):

        if len(props) > 2:
            if (~props[2].isspace()) and (props[2] != ''):
                expr = ConstraintParser(props[2], self)
                expr.evaluate(component_name, par_name)

                self.constraints += [expr.constraint]

    def _kinematic_constraints(self):

        cn = self.k_component_names
        kg = self.k_groups

        components = []
        for i in set(kg):
            components += [[cn[j] for j in range(len(cn)) if i == kg[j]]]

        for i, g in enumerate(components):
            if len(g) > 1:
                for j in range(len(g[:-1])):
                    wla = self.__idx__(g[j], 'wavelength')
                    rest0 = copy.deepcopy(self.p0[wla])
                    wlb = self.__idx__(g[j + 1], 'wavelength')
                    rest1 = copy.deepcopy(self.p0[wlb])
                    sa = self.__idx__(g[j], 'sigma')
                    sb = self.__idx__(g[j + 1], 'sigma')
                    self.constraints += [
                        spectools.Constraints.redshift(
                            wla, wlb, rest0, rest1)]
                    self.constraints += [
                        spectools.Constraints.sigma(sa, sb, wla, wlb)]

        self.k_components = components

    def parse_line(self, line):

        line_pars = self.cfg[line]
        for par in self.par_names:
            props = line_pars[par].split(',')
            if props[0] not in ['peak', 'mean', 'median']:
                self.p0 += [float(props[0])]
            else:
                self.p0 += [props[0]]
            self._bounds(props)

        if 'k_group' in line_pars:
            self.k_groups += [line_pars.getint('k_group')]
            self.k_component_names += [line]

        self._continuumWindows(line, line_pars)

    def get_vars(self):

        d = {**vars(self), **self.fit_opts}
        todel = [
            'cfg', 'par_names', 'fit_opts', 'copts',
            'k_groups', 'k_components', 'k_component_names', 'cwin']
        for i in todel:
            del d[i]
        d['copts'] = self.copts
        d['constraints'] = self.constraints
        return d