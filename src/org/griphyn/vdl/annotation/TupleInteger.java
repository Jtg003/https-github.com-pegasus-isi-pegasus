/*
 * This file or a portion of this file is licensed under the terms of
 * the Globus Toolkit Public License, found in file GTPL, or at
 * http://www.globus.org/toolkit/download/license.html. This notice must
 * appear in redistributions of this file, with or without modification.
 *
 * Redistributions of this Software, with or without modification, must
 * reproduce the GTPL in: (1) the Software, or (2) the Documentation or
 * some other similar material which is provided with the Software (if
 * any).
 *
 * Copyright 1999-2004 University of Chicago and The University of
 * Southern California. All rights reserved.
 */
package org.griphyn.vdl.annotation;

/**
 * This simple class defines the long values for the values at the heart of Yong's annotations.
 *
 * @author Jens-S. Vöckler
 * @author Yong Zhao
 * @version $Revision$
 */
public class TupleInteger extends Tuple {
    /** Defines the key for which we store the annotation. */
    private long m_value = 0;

    /**
     * Constructs an instance of a long tuple.
     *
     * @param key is the key to store annotations for.
     * @param value is the long value of the annotation.
     */
    public TupleInteger(String key, long value) {
        super(key);
        m_value = value;
    }

    /**
     * Obtains the current value of the value part.
     *
     * @return the current value as long.
     * @see #setLong( long )
     */
    public long getLong() {
        return m_value;
    }

    /**
     * Overwrites the current value of the value part.
     *
     * @param value is the new value to use from now on.
     * @see #getLong()
     */
    public void setLong(long value) {
        m_value = value;
    }

    /**
     * Return generically the value wrapped into a Java class.
     *
     * @return the value wrapped as Java object.
     * @see #setValue( Object )
     * @see java.lang.Long
     */
    public Object getValue() {
        return new Long(m_value);
    }

    /**
     * Generic interface to set a value in an instance. Note that this action may fail, if the
     * instance is of an incompatible type.
     *
     * @param value is the data object to set.
     * @see #getValue()
     * @exception ClassCastException if the actual argument type of the value is incompatible with
     *     the value maintained by the instance.
     */
    public void setValue(Object value) throws ClassCastException {
        if (value instanceof java.lang.Number) m_value = ((Long) value).longValue();
        else if (value instanceof java.lang.String) m_value = Long.parseLong((String) value);
        else throw new ClassCastException("type cast failed: not a Long");
    }

    /**
     * Returns the type of the value as SQL Type.
     *
     * @return a constant from the set of SQL types.
     * @see java.sql.Types
     */
    public int getType() {
        return java.sql.Types.BIGINT;
    }

    /** Returns the string representation of the type. */
    public String getTypeString() {
        return "int";
    }
}
